import os,json,urllib,uuid,sqlite3

from flask import (
    Flask, render_template, request, abort, Blueprint, flash, g, redirect, render_template, request, session, url_for, abort
)

import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db
import matrix_twilio_bridge.util as util

db = matrix_twilio_bridge.db.db
config = matrix_twilio_bridge.util.config
bp = Blueprint('matrix', __name__, url_prefix='/matrix')
matrix_headers = {"Authorization":"Bearer "+config['access_token']}
matrix_base_url = 'http://' + config["homeserver"]

def confirm_auth(request):
    if not "access_token" in request.args:
        abort(401)
    if not request.args["access_token"] == config['hs_token']:
        abort(403)

@bp.route('/app/v1/transactions/<txnId>', methods=['PUT'])
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
        room_members = util.get_room_members(room_id)
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
            twilio_author = util.get_conversation_author(sender,conversation_sid)
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
                    text = event["content"]["body"]
                    if text == "!config":
                        config_url = config["base_url"] + "/config/" + db.updateAuthToken(sender) + "/"
                        util.sendMsgToRoom(room_id, "@twilio_bot:"+config["homeserver"] , config_url)
                    print(event["content"]["body"])
            
    return {}

@bp.route('/app/v1/users/<userId>', methods=['GET'])
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

@bp.route('/app/v1/rooms/<roomAlias>', methods=['GET'])
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
