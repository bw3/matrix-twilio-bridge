import os,json,urllib,uuid,sqlite3,configparser

from flask import (Flask, render_template, request, abort)
import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db 

db = matrix_twilio_bridge.db.db
config = configparser.ConfigParser()
config.read('config')

def get_conversation_participants(matrix_id,conversation_sid):
    twilio_client = getTwilioClient(matrix_id)
    participants = twilio_client.conversations.conversations(conversation_sid).participants.list(limit=50)
    response = []
    for record in participants:
        if "address" in record.messaging_binding:
            response.append(record.messaging_binding["address"])
        if "proxy_address" in record.messaging_binding:
            response.append(record.messaging_binding["proxy_address"])
        if "projected_address" in record.messaging_binding:
            response.append(record.messaging_binding["projected_address"])
    return response

def get_conversation_author(matrix_id,conversation_sid):
    twilio_client = getTwilioClient(matrix_id)
    conversation_participants = set(get_conversation_participants(matrix_id,conversation_sid))
    incoming_phone_numbers = set()
    result = twilio_client.incoming_phone_numbers.list()
    for entry in result:
        incoming_phone_numbers.add(entry.phone_number)
    for match in (incoming_phone_numbers | conversation_participants):
        return match
    

def get_room_members(room_id):
    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = getMatrixHeaders())
    return r.json()['joined'].keys()

def getRoomId(matrix_username, conversation_sid=None, to_number="", from_number=""):
    twilio_client = getTwilioClient(matrix_username)
    if conversation_sid is None:
        conversations = twilio_client.conversations.conversations.list()
        for record in conversations:
            participants = twilio_client.conversations.conversations(record.sid).participants.list()
            for participant in participants:
                if participant.messaging_binding.get("address","") == from_number and participant.messaging_binding.get("proxy_address","") == to_number:
                    conversation_sid = record.sid
    if conversation_sid is None:
        conversation_sid = twilio_client.conversations.conversations.create().sid
        twilio_client.conversations.conversations(conversation_sid).participants.create(
            messaging_binding_address=from_number,
            messaging_binding_proxy_address=to_number
        )
    room_id = db.getRoomId(matrix_username, conversation_sid)
    if room_id is not None:
        setRoomUsers(matrix_username, room_id, conversation_sid)
        return room_id
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/createRoom', headers = getMatrixHeaders(), json = { "preset": "private_chat" })
    if r.status_code != 200:
        abort(500)
    room_id = r.json()['room_id']
    db.linkRoomConversation(matrix_username, room_id, conversation_sid)
    setRoomUsers(matrix_username, room_id, conversation_sid)
    return room_id
    

def addUserToRoom(room_id, username) :
    user_data = { 
        "username": username.split(':')[0].removeprefix('@')
    }
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/register', headers = getMatrixHeaders(), json = user_data)
    invite_data = {
        "user_id": username
    }
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/invite', headers = getMatrixHeaders(), json = invite_data)
    if not isTwilioUser(username):
        return
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/join', headers = getMatrixHeaders(), params={"user_id":username})
    if r.status_code != 200:
        abort(500)

def removeUserFromRoom(room_id, username):
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/leave', headers = getMatrixHeaders(), params={"user_id":username})
    if r.status_code != 200:
        abort(500)

def setRoomUsers(matrix_username, room_id, conversation_sid):
    room_users = get_conversation_participants(matrix_username,conversation_sid)
    for i in range(len(room_users)):
        room_users[i] = getMatrixId(room_users[i])
    room_users.append(getBotMatrixId())
    room_users.append(matrix_username)
    username_set_goal = set(room_users)

    username_set_current = set()
    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = getMatrixHeaders())#, params={"user_id":"twilio_bot"})

    for username in r.json()['joined'].keys():
        username_set_current.add(username)

    for username in username_set_current:
        if username not in username_set_goal:
            removeUserFromRoom(room_id,username)

    for username in username_set_goal:
        if username not in username_set_current:
            addUserToRoom(room_id,username)

    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = getMatrixHeaders())

def sendMsgToRoom(room_id, username, text):
    msg_data = {
        "msgtype": "m.text",
        "body": text
    }
    r = requests.put(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = getMatrixHeaders(), json = msg_data, params={"user_id":username} )

def postFileToRoom(room_id, username, mimetype, data, filename):
    r = requests.post(getHomeserverAddress() + '/_matrix/media/r0/upload', data=data, headers = getMatrixHeaders() | {'Content-Type':mimetype})
    if r.status_code != 200:
        abort(500)
    content_uri = r.json()["content_uri"]
    if mimetype.lower().startswith("image"):
        msgtype = "m.image"
    elif mimetype.lower().startswith("audio"):
        msgtype = "m.audio"
    elif mimetype.lower().startswith("video"):
        msgtype = "m.video"
    else:
        msgtype = "m.file"
    msg_data = {
        "msgtype": msgtype,
        "body": filename,
        "url": content_uri,
        "info": {
            "mimetype": mimetype
        }
    }
    r = requests.put(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = getMatrixHeaders(), json = msg_data, params={"user_id":username} )

def getTwilioClient(matrix_id):
    try:
        (sid,auth) = db.getTwilioAuthPair(matrix_id)
    except:
        return None
    twilio_client = TwilioClient(sid,auth)
    return twilio_client

def adjustUrl(url,adjust):
    idx = url.rfind('/')
    return url[0:idx+1]+adjust

def getIncomingNumberConfig(matrix_id, number):
    config = db.getIncomingNumberConfig(matrix_id, number)
    if config is None:
        config = {}
    else:
        config = json.loads(config)
    config.setdefault("hunt_enabled", False)
    config.setdefault("hunt_timeout", 60)
    config.setdefault("hunt_numbers",[])
    config.setdefault("voicemail_enabled", False)
    config.setdefault("voicemail_tts","Please leave your message after the tone")
    config.setdefault("voicemail_timeout", 300)
    config.setdefault("voicemail_transcribe", False)
    return config

def getHomeserverDomain():
    return config["homeserver"]["domain"]

def getHomeserverAddress():
    return config["homeserver"]["address"]

def getAppserviceAsToken():
    return config["appservice"]["as_token"]

def getAppserviceHsToken():
    return config["appservice"]["hs_token"]

def getAppserviceAddress():
    return config["appservice"]["address"]

def getMatrixHeaders():
    return {"Authorization":"Bearer "+getAppserviceAsToken()}

def isTwilioBot(matrix_id):
    return matrix_id == getBotMatrixId()

def isTwilioUser(matrix_id):
    return matrix_id.startswith("@"+ config["appservice"]["id"]) and not isTwilioBot(matrix_id)

def getMatrixId(phoneNumber):
    return "@" + config["appservice"]["id"] +  phoneNumber + ":" + getHomeserverDomain()

def getBotMatrixId():
    return "@" + config["appservice"]["bot_username"] + ":" + getHomeserverDomain()
