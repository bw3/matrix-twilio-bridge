import os,json,urllib,uuid,sqlite3

from flask import (Flask, render_template, request, abort)
import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db 

def create_app():
    app = Flask(__name__)
    with open('config') as f:
       config = json.load(f)
    matrix_headers = {"Authorization":"Bearer "+config['access_token']}
    matrix_base_url = 'http://' + config["homeserver"]
    db = matrix_twilio_bridge.db.DB()

    @app.route('/')
    def hello():
        return {}

    def confirm_auth(request):
        if not "access_token" in request.args:
            abort(401)
        if not request.args["access_token"] == config['hs_token']:
            abort(403)

    def get_conversation_participants(matrix_id,conversation_sid):
        twilio_client = TwilioClient(config["users"][matrix_id]["twilio_sid"], config["users"][matrix_id]["twilio_auth"])
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
        twilio_client = TwilioClient(config["users"][matrix_id]["twilio_sid"], config["users"][matrix_id]["twilio_auth"])
        conversation_participants = set(get_conversation_participants(matrix_id,conversation_sid))
        incoming_phone_numbers = set()
        result = twilio_client.incoming_phone_numbers.list(limit=20)
        for entry in result:
            incoming_phone_numbers.add(entry.phone_number)
        for match in (incoming_phone_numbers | conversation_participants):
            return match
        

    def get_room_members(room_id):
        r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)
        return r.json()['joined'].keys()

    @app.route('/transactions/<txnId>', methods=['PUT'])
    @app.route('/_matrix/app/v1/transactions/<txnId>', methods=['PUT'])
    def matrix_event(txnId):
        confirm_auth(request)
        json = request.get_json()
        for event in json["events"]:
            sender = event["sender"]
            room_id = event["room_id"]
            print(event)
            if "state_key" in event:
                if event["type"] == "m.room.member" and event["content"]["membership"] == "invite":
                    username = event["state_key"]
                    if username.startswith("@twilio_"):
                        r = requests.post(matrix_base_url + '/_matrix/client/r0/rooms/'+room_id+'/join', headers = matrix_headers, params={"user_id":username})
                        print(r)
                return {}
            room_members = get_room_members(room_id)
            room_contains_phone = False
            room_contains_bot = False
            print(room_members)
            for member in room_members:
                if member.startswith("@twilio_+"):
                    room_contains_phone = True
                if member.startswith("@twilio_bot"):
                    room_contains_bot = True
            if room_contains_phone:
                if sender not in config["users"]:
                    print("User {} not configured".format(sender))
                    return {}
                twilio_client = TwilioClient(config["users"][sender]["twilio_sid"], config["users"][sender]["twilio_auth"])
                twilio_auth = (config["users"][sender]["twilio_sid"], config["users"][sender]["twilio_auth"])
                conversation_sid = db.getConversationSid(sender,room_id)
                twilio_author = get_conversation_author(sender,conversation_sid)
                print(twilio_author)
                if event["type"] == "m.room.message":
                    if event["content"]["msgtype"] == "m.text":
                        if sender not in config["users"]:
                            print(sender + " not configured")
                            return {}
                        text = event["content"]["body"]
                        room_id = event["room_id"]
                        print(event["sender"] + ": " + event["content"]["body"])
                        conversation_sid = db.getConversationSid(sender,room_id)
                        twilio_client.conversations.conversations(conversation_sid).messages.create(author=twilio_author, body=text)
                    elif event["content"]["msgtype"] in ["m.image", "m.file", "m.audio", "m.video"]:
                        url = event["content"]["url"]
                        if url is None or not url.startswith("mxc://"):
                            print("Not a mxc url "+ url)
                            return {}
                        url = url[6:]
                        chat_service_sid = twilio_client.conversations.conversations(conversation_sid).fetch().chat_service_sid
                        r = requests.get(matrix_base_url + '/_matrix/media/r0/download/' + url, headers = matrix_headers, stream=True)
                        file_bytes = r.content
                        hdrs = {"Content-Type": r.headers["content-type"]}
                        r = requests.post('https://mcs.us1.twilio.com/v1/Services/' + chat_service_sid + '/Media', data = file_bytes, auth=twilio_auth, headers = hdrs)
                        print(r)
                        print(r.json())
                        media_sid = r.json()["sid"]
                        twilio_client.conversations.conversations(conversation_sid).messages.create(author=twilio_author, media_sid=media_sid)
            elif room_contains_bot:
                if event["type"] == "m.room.message":
                    if event["content"]["msgtype"] == "m.text":
                        print(event["content"]["body"])
                
        return {}

    @app.route('/users/<userId>', methods=['GET'])
    @app.route('/_matrix/app/v1/users/<userId>', methods=['GET'])
    def matrix_user_exists(userId):
        print('matrix_user_exists')
        confirm_auth(request)
        user_data = {
            "username": userId.split(':')[0].removeprefix('@')
        }
        r = requests.post(matrix_base_url + '/_matrix/client/r0/register', headers = matrix_headers, json = user_data, params={"user_id":"@twilio_bot:"+config["homeserver"]})
        if r.status_code != 200:
            abort(500)
        return {}

    @app.route('/rooms/<roomAlias>', methods=['GET'])
    @app.route('/_matrix/app/v1/rooms/<roomAlias>', methods=['GET'])
    def matrix_room_exists(roomAlias):
        print('matrix_room_exists')
        confirm_auth(request)
        room_data = {
            "preset": "private_chat",
            "room_alias_name": roomAlias.split(':')[0].removeprefix('#'),
        }
        print(room_data)
        r = requests.post(matrix_base_url + '/_matrix/client/r0/createRoom', headers = matrix_headers, json = room_data)#, params={"user_id":"@twilio_bot:"+config["homeserver"]})
        print(r.text)
        if r.status_code != 200:
            abort(500)
        room_id = r.json()['room_id']
        r = requests.post(matrix_base_url + '/_matrix/client/r0/rooms/'+ room_id + '/join', headers = matrix_headers)
        print(r)
        return {}

    @app.route('/twilio/<matrix_username>', methods=['POST'])
    def twilio_msg_recieved(matrix_username):
        print(request.form)
        author = "@twilio_" + request.form['Author'] + ":" + config["homeserver"]
        conversation_sid = request.form['ConversationSid']
        room_id = getRoomId(matrix_username, conversation_sid)
        room_users = get_conversation_participants(matrix_username,conversation_sid)
        for i in range(len(room_users)):
            room_users[i] = "@twilio_" +  room_users[i]+ ":" + config["homeserver"]
        room_users.append("@twilio_bot:"+config["homeserver"])
        room_users.append(matrix_username)    
        setRoomUsers(room_id, set(room_users))
        if 'Media' in request.form:
            twilio_client = TwilioClient(config["users"][matrix_username]["twilio_sid"], config["users"][matrix_username]["twilio_auth"])
            twilio_auth = (config["users"][matrix_username]["twilio_sid"], config["users"][matrix_username]["twilio_auth"])
            chat_service_sid = twilio_client.conversations.conversations(conversation_sid).fetch().chat_service_sid
            media = json.loads(request.form['Media'])
            for entry in media:
                media_sid = entry["Sid"]
                content_type = entry["ContentType"]
                filename = entry["Filename"]
                r = requests.get("https://mcs.us1.twilio.com/v1/Services/" + chat_service_sid + "/Media/" + media_sid + "/Content", auth=twilio_auth)
                print(r)
                postFileToRoom(room_id, author, content_type, r.content, filename)
        if 'Body' in request.form:
            text = request.form['Body']
            sendMsgToRoom(room_id,author, text)
        return {}

    @app.route('/test', methods=['GET'])
    def test():
        return {}

    def getRoomId(matrix_username, conversation_sid):
        room_id = db.getRoomId(matrix_username, conversation_sid)
        if room_id is not None:
            return room_id
        r = requests.post(matrix_base_url + '/_matrix/client/r0/createRoom', headers = matrix_headers, json = { "preset": "private_chat" })#, params={"user_id":"@twilio_bot:"+config["homeserver"]})
        print(r.text)
        if r.status_code != 200:
            abort(500)
        room_id = r.json()['room_id']
        db.linkRoomConversation(matrix_username, room_id, conversation_sid)
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

    def setRoomUsers(room_id, username_set_goal):
        username_set_current = set()
        print('setRoomUsers')
        r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)#, params={"user_id":"twilio_bot"})
        print('setRoomUsers')

        for username in r.json()['joined'].keys():
            username_set_current.add(username)
        print('setRoomUsers')

        for username in username_set_current:
            if username not in username_set_goal:
                print('remove ' + username)
                removeUserFromRoom(room_id,username)
        print('setRoomUsers')

        for username in username_set_goal:
            if username not in username_set_current:
                addUserToRoom(room_id,username)
        print('setRoomUsers')

        r = requests.get(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id  + '/joined_members', headers = matrix_headers)
        print(r.json())

    def sendMsgToRoom(room_id, username, text):
        msg_data = {
            "msgtype": "m.text",
            "body": text
        }
        r = requests.put(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = matrix_headers, json = msg_data, params={"user_id":username} )

    def postFileToRoom(room_id, username, mimetype, data, filename):
        r = requests.post(matrix_base_url + '/_matrix/media/r0/upload', data=data, headers = matrix_headers | {'Content-Type':mimetype})
        if r.status_code != 200:
            print(r.text)
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
        print(msg_data)
        r = requests.put(matrix_base_url + '/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message/'+str(uuid.uuid4()), headers = matrix_headers, json = msg_data, params={"user_id":username} )

    

    return app

