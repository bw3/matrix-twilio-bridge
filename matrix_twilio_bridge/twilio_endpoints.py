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
bp = Blueprint('twilio', __name__, url_prefix='/twilio')

@bp.route('/<matrix_username>', methods=['POST'])
def twilio_msg_recieved(matrix_username):
    print(request.form)
    author = "@twilio_" + request.form['Author'] + ":" + config["homeserver"]
    conversation_sid = request.form['ConversationSid']
    room_id = util.getRoomId(matrix_username, conversation_sid)
    room_users = util.get_conversation_participants(matrix_username,conversation_sid)
    for i in range(len(room_users)):
        room_users[i] = "@twilio_" +  room_users[i]+ ":" + config["homeserver"]
    room_users.append("@twilio_bot:"+config["homeserver"])
    room_users.append(matrix_username)    
    util.setRoomUsers(room_id, set(room_users))
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
            util.postFileToRoom(room_id, author, content_type, r.content, filename)
    if 'Body' in request.form:
        text = request.form['Body']
        util.sendMsgToRoom(room_id,author, text)
    return {}
