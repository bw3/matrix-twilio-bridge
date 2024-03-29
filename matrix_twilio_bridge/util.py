import os,json,urllib,uuid,sqlite3,configparser,traceback,datetime

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
    json = {
        "preset": "private_chat"
    }
    twilio_client = getTwilioClient(matrix_id)
    is_direct = len(numbers) == 2
    (twilio_number, non_twilio_numbers) = validateNumbers(matrix_id,numbers)
    if is_direct:
        phone_number = non_twilio_numbers[0]
        matrix_id_phone = getMatrixId(matrix_id,phone_number)
        json["is_direct"] = True
        json["invite"] = [matrix_id, matrix_id_phone]
        displayname = db.getDisplayName(matrix_id,phone_number)
        if displayname is None:
            displayname = phone_number
        else:
            displayname += ' ({0})'.format(phone_number)
        createUser(matrix_id_phone,displayname)
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/createRoom', headers = getMatrixHeaders(), json=json)
    room_id = r.json()['room_id']
    db.setRoomForNumbers(matrix_id, room_id, numbers)
    json = {
        "ban":100,
        "invite":100,
        "kick":100,
        "events": {
            "m.room.name": 0,
            "m.room.power_levels": 100
        },
        "events_default":0,
        "users": {
            getBotMatrixId(): 100
        }
    }
    r = requests.put(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+urllib.parse.quote(room_id)+'/state/m.room.power_levels', headers = getMatrixHeaders(), json=json)
    r.json()
    setRoomUsers(matrix_id, room_id)
    return room_id
    
def findConversationAndAuthor(matrix_id,room_id):
    numbers = set()
    for mid in get_room_members(room_id):
        if isTwilioUser(mid):
            numbers.add(getPhoneNumber(matrix_id,mid))
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

def createUser(username, displayname):
    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/profile/' + username  + '/displayname', headers = getMatrixHeaders())
    exists = r.status_code != 404
    if not exists:
        user_data = {
            "type": "m.login.application_service",
            "username": username.split(':')[0].removeprefix('@')
        }
        r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/register', headers = getMatrixHeaders(), json = user_data)
        r.json()
    if displayname is not None:
        json_body = {"displayname":displayname}
        r = requests.put(getHomeserverAddress() + '/_matrix/client/r0/profile/' + username  + '/displayname', headers = getMatrixHeaders(), json = json_body, params={"user_id":username})
        r.json()

def setDisplayName(matrix_id_human, phone_number, displayname):
    if displayname == '':
        displayname = None
    db.setDisplayName(matrix_id_human, phone_number, displayname)
    id_ = db.getIdForPhoneNumber(matrix_id_human, phone_number)
    if id_ is None:
        return
    matrix_id_phone = "@" + config["appservice"]["id"] + id_ + ":" + getHomeserverDomain()
    if displayname is None:
        displayname = phone_number
    else:
        displayname += ' ({0})'.format(phone_number)
    if matrix_id_phone is not None:
        createUser(matrix_id_phone, displayname)

def addUserToRoom(room_id, username, displayname=None):
    createUser(username, displayname)
    invite_data = {
        "user_id": username
    }
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/invite', headers = getMatrixHeaders(), json = invite_data)
    r = requests.post(getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/join', headers = getMatrixHeaders(), params={"user_id":username})

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
        room_users.append(getMatrixId(matrix_id, number))
    room_users.append(getBotMatrixId())
    room_users.append(matrix_id)
    username_set_goal = set(room_users)

    username_set_current = set()
    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id  + '/members', headers = getMatrixHeaders())

    for record in r.json()['chunk']:
        if record["content"]["membership"] in ["join","invite"]:
            username_set_current.add(record["state_key"])

    for username in username_set_current:
        if username not in username_set_goal:
            removeUserFromRoom(room_id,username)

    for username in username_set_goal:
        if username not in username_set_current:
            if isTwilioUser(username):
                phone_number = getPhoneNumber(matrix_id,username)
                displayname = db.getDisplayName(matrix_id, phone_number)
                if displayname is None:
                    displayname = phone_number
                else:
                    displayname += ' ({0})'.format(phone_number)
            else:
                displayname = None
            addUserToRoom(room_id,username, displayname)

    r = requests.get(getHomeserverAddress() + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = getMatrixHeaders())

def sendNoticeToRoom(room_id, username, text):
    sendMsgToRoom(room_id, username, text, True)

def sendMsgToRoom(room_id, username, text, notice=False):
    msg_data = {
        "body": text
    }
    if notice:
        msg_data["msgtype"] = "m.notice"
    else:
        msg_data["msgtype"] = "m.text"
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

def postVoicemailToRoom(room_id, username, mimetype, data, filename, seconds):
    r = requests.post(getHomeserverAddress() + '/_matrix/media/r0/upload', data=data, headers = getMatrixHeaders() | {'Content-Type':mimetype})
    if r.status_code != 200:
        abort(500)
    content_uri = r.json()["content_uri"]
    msg_data = {
        "msgtype": "m.audio",
        "body": filename,
        "url": content_uri,
        "info": {
            "mimetype": mimetype,
            "duration": seconds
        },
        "org.matrix.msc3245.voice": {}
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

def recv_twilio_msg(matrix_id,conversation_sid,message_sid):
    twilio_client = getTwilioClient(matrix_id)
    message = twilio_client.conversations.conversations(conversation_sid).messages(message_sid).fetch()
    author = getMatrixId(matrix_id,message.author)
    numbers = get_conversation_participants(matrix_id,conversation_sid)
    room_id = findRoomId(matrix_id,numbers,conversation_sid)
    if message.media is not None:
        twilio_auth = db.getTwilioAuthPair(matrix_id)
        chat_service_sid = twilio_client.conversations.conversations(conversation_sid).fetch().chat_service_sid
        for entry in message.media:
            media_sid = entry["sid"]
            content_type = entry["content_type"]
            filename = entry["filename"]
            r = requests.get("https://mcs.us1.twilio.com/v1/Services/" + chat_service_sid + "/Media/" + media_sid + "/Content", auth=twilio_auth)
            postFileToRoom(room_id, author, content_type, r.content, filename)
    if message.body is not None:
        text = message.body
        sendMsgToRoom(room_id,author, text)
    twilio_client.conversations.conversations(conversation_sid).messages(message_sid).delete()

def cron():
    no_errors = True
    for matrix_id in db.allMatrixIds():
        print(matrix_id)
        try:
            twilio_client = getTwilioClient(matrix_id)
            incoming_phone_numbers = twilio_client.incoming_phone_numbers.list(limit=20)
            numbers = set()
            for record in incoming_phone_numbers:
                numbers.add(record.phone_number)
            missed_messages = 0
            for conversation in twilio_client.conversations.conversations.list():
                for message in conversation.messages.list():
                    if message.author in numbers:
                        if datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1) > message.date_created:
                            message.delete()
                    else:
                        if datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1) > message.date_created:
                            recv_twilio_msg(matrix_id,conversation.sid,message.sid)
                            missed_messages += 1
            print('  Processed {0} missed messages. '.format(missed_messages))
        except:
            traceback.print_exc()
            no_errors = False
    return no_errors

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

def getPhoneNumber(matrix_id_human, matrix_id_phone):
    id_ = matrix_id_phone.split(':')[0].removeprefix('@' + config["appservice"]["id"])
    return db.getPhoneNumberForId(matrix_id_human, id_)

def getMatrixId(matrix_id, phone_number):
    id_ = db.getIdForPhoneNumber(matrix_id, phone_number)
    if id_ is None:
        db.generateIdForPhoneNumber(matrix_id, phone_number)
        id_ = db.getIdForPhoneNumber(matrix_id, phone_number)
    return "@" + config["appservice"]["id"] + id_ + ":" + getHomeserverDomain()

def getBotMatrixId():
    return "@" + config["appservice"]["bot_username"] + ":" + getHomeserverDomain()
