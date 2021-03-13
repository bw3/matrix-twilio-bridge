import os,json,urllib,uuid,sqlite3,configparser, traceback

from flask import (Flask, render_template, request, abort)
import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db 

db = matrix_twilio_bridge.db.db
config = configparser.ConfigParser(allow_no_value=True,delimiters=('=',))
config.read('config')

def validateNumbers(matrix_id,numbers):
    twilio_client = getTwilioClient(matrix_id)
    numbers = set(numbers)
    num_incoming_phone_numbers = 0
    for entry in twilio_client.incoming_phone_numbers.list():
        if entry.phone_number in numbers:
            num_incoming_phone_numbers += 1
            twilio_number = entry.phone_number
    if num_incoming_phone_numbers < 1:
        raise Exception('No twilio number found')
    if num_incoming_phone_numbers > 1:
        raise Exception('More than 1 twilio number found')
    if len(numbers) < 2:
        raise Exception('Missing phone number')
    numbers.remove(twilio_number)
    return (twilio_number, list(numbers))

def createRoom(matrix_id,numbers):
    twilio_client = getTwilioClient(matrix_id)
    validateNumbers(matrix_id,numbers)
    is_direct = len(numbers) == 2
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/createRoom', headers = getMatrixHeaders(), json = { "preset": "private_chat", "is_direct":is_direct})
    room_id = r.json()['room_id']
    db.setRoomForNumbers(matrix_id, room_id, numbers)
    setRoomUsers(matrix_id, room_id)
    return room_id
    
def findConversationAndAuthor(matrix_id,room_id):
    numbers = set()
    for mid in get_room_members(room_id):
        if isTwilioUser(mid):
            numbers.add(getPhoneNumber(mid))
    twilio_client = getTwilioClient(matrix_id)
    db.setRoomForNumbers(matrix_id,room_id,numbers)
    conversation_sid = db.getConversationSid(matrix_id,numbers)
    (twilio_number,other_numbers) = validateNumbers(matrix_id,numbers)
    if conversation_sid is not None:
        try:
            conversation = twilio_client.conversations.conversations(conversation_sid)
            conversation.fetch()
            return (conversation,twilio_number)
        except:
            pass
    conversation = twilio_client.conversations.conversations.create()
    if len(other_numbers) == 1:
        conversation.participants.create(
            messaging_binding_proxy_address=twilio_number,
            messaging_binding_address=other_numbers[0]
        )
    else:
        for to_number in other_numbers:
            conversation.participants.create(messaging_binding_address=to_number)
        conversation.participants.create(messaging_binding_projected_address=twilio_number)
    db.setConversationSidForNumbers(matrix_id,conversation.sid,numbers)
    return (conversation,twilio_number)

def findRoomId(matrix_id,numbers,conversation_sid=None):
    room_id = db.getRoomId(matrix_id,numbers)
    if room_id is None:
        room_id = createRoom(matrix_id,numbers)
    else:
        setRoomUsers(matrix_id, room_id)
    if conversation_sid is not None:
        db.setConversationSidForNumbers(matrix_id,conversation_sid,numbers)
    return room_id

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

def addUserToRoom(room_id, username) :
    user_data = { 
        "username": username.split(':')[0].removeprefix('@')
    }
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/register', headers = getMatrixHeaders(), json = user_data)
    invite_data = {
        "user_id": username
    }
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/invite', headers = getMatrixHeaders(), json = invite_data)

def removeUserFromRoom(room_id, username):
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/leave', headers = getMatrixHeaders(), params={"user_id":username})
    if r.status_code != 200:
        abort(500)

def setRoomUsers(matrix_id, room_id):
    numbers = db.getNumbersForRoomId(matrix_id, room_id)
    if numbers is None:
        return
    room_users = []
    for number in  numbers:
        room_users.append(getMatrixId(number))
    room_users.append(getBotMatrixId())
    room_users.append(matrix_id)
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

def isMatrixIdAllowed(matrix_id):
    for permission in config["permissions"].keys():
        if permission == '*':
            return True
        elif permission.startswith('@'):
            if permission == matrix_id:
                return True
        elif permission == matrix_id.split(':',maxsplit=1)[1]:
            return True
    return False

def getMatrixHeaders():
    return {"Authorization":"Bearer "+getAppserviceAsToken()}

def isTwilioBot(matrix_id):
    return matrix_id == getBotMatrixId()

def isTwilioUser(matrix_id):
    return matrix_id.startswith("@"+ config["appservice"]["id"]) and matrix_id.endswith(getHomeserverDomain()) and not isTwilioBot(matrix_id)

def getPhoneNumber(matrix_id):
    return matrix_id.split(':')[0].removeprefix('@' + config["appservice"]["id"])

def getMatrixId(phoneNumber):
    return "@" + config["appservice"]["id"] +  phoneNumber + ":" + getHomeserverDomain()

def getBotMatrixId():
    return "@" + config["appservice"]["bot_username"] + ":" + getHomeserverDomain()
