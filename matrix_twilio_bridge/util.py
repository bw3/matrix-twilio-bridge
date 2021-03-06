import os,json,urllib,uuid,sqlite3

from flask import (Flask, render_template, request, abort)
import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db 

db = matrix_twilio_bridge.db.db
with open('config') as f:
   config = json.load(f)
matrix_headers = {"Authorization":"Bearer "+config['access_token']}
matrix_base_url = 'http://' + config["homeserver"]

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
    r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)
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
    r = requests.post(matrix_base_url + '/_matrix/client/r0/createRoom', headers = matrix_headers, json = { "preset": "private_chat" })#, params={"user_id":"@twilio_bot:"+config["homeserver"]})
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
    r = requests.post(matrix_base_url + '/_matrix/client/r0/register', headers = matrix_headers, json = user_data)
    invite_data = {
        "user_id": username
    }
    r = requests.post(matrix_base_url + '/_matrix/client/r0/rooms/'+room_id+'/invite', headers = matrix_headers, json = invite_data)
    if not username.startswith("@twilio_"):
        return
    r = requests.post(matrix_base_url + '/_matrix/client/r0/rooms/'+room_id+'/join', headers = matrix_headers, params={"user_id":username})
    if r.status_code != 200:
        abort(500)

def removeUserFromRoom(room_id, username):
    r = requests.post(matrix_base_url + '/_matrix/client/r0/rooms/'+room_id+'/leave', headers = matrix_headers, params={"user_id":username})
    if r.status_code != 200:
        abort(500)

def setRoomUsers(matrix_username, room_id, conversation_sid):
    room_users = get_conversation_participants(matrix_username,conversation_sid)
    for i in range(len(room_users)):
        room_users[i] = "@twilio_" +  room_users[i]+ ":" + config["homeserver"]
    room_users.append("@twilio_bot:"+config["homeserver"])
    room_users.append(matrix_username)
    username_set_goal = set(room_users)

    username_set_current = set()
    r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)#, params={"user_id":"twilio_bot"})

    for username in r.json()['joined'].keys():
        username_set_current.add(username)

    for username in username_set_current:
        if username not in username_set_goal:
            removeUserFromRoom(room_id,username)

    for username in username_set_goal:
        if username not in username_set_current:
            addUserToRoom(room_id,username)

    r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)

def sendMsgToRoom(room_id, username, text):
    msg_data = {
        "msgtype": "m.text",
        "body": text
    }
    r = requests.put(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = matrix_headers, json = msg_data, params={"user_id":username} )

def postFileToRoom(room_id, username, mimetype, data, filename):
    r = requests.post(matrix_base_url + '/_matrix/media/r0/upload', data=data, headers = matrix_headers | {'Content-Type':mimetype})
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
    r = requests.put(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = matrix_headers, json = msg_data, params={"user_id":username} )

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

