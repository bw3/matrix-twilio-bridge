import os, json, urllib, uuid, sqlite3, traceback

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

def confirm_auth(request):
    if not "access_token" in request.args:
        abort(401)
    if not request.args["access_token"] == util.getAppserviceHsToken():
        abort(403)

@bp.route('/app/v1/transactions/<txnId>', methods=['PUT'])
def matrix_event(txnId):
    confirm_auth(request)
    json = request.get_json()
    for event in json["events"]:
        sender = event["sender"]
        room_id = event["room_id"]
        if "state_key" in event:
            if event["type"] == "m.room.member" and event["content"]["membership"] == "invite":
                username = event["state_key"]
                if util.isTwilioUser(username) or util.isTwilioBot(username):
                    r = requests.post(util.getHomeserverAddress() + '/_matrix/client/r0/rooms/'+room_id+'/join', headers = util.getMatrixHeaders(), params={"user_id":username})
            return {}
        room_members = util.get_room_members(room_id)
        room_contains_phone = False
        room_contains_bot = False
        for member in room_members:
            if util.isTwilioUser(member):
                room_contains_phone = True
            if util.isTwilioBot(member):
                room_contains_bot = True
        if util.isTwilioUser(sender) or util.isTwilioBot(sender):
            return {}
        if room_contains_phone:
            try:
                if not util.isMatrixIdAllowed(sender):
                    raise Exception('You are not allowed access to the bridge. ')
                twilio_auth = db.getTwilioAuthPair(sender)
                (conversation, twilio_author) = util.findConversationAndAuthor(sender,room_id)
                if event["type"] == "m.room.message":
                    if event["content"].get("msgtype","") == "m.text":
                        text = event["content"]["body"]
                        room_id = event["room_id"]
                        conversation.messages.create(author=twilio_author, body=text)
                    elif event["content"].get("msgtype","") in ["m.image", "m.file", "m.audio", "m.video"]:
                        url = event["content"]["url"]
                        if url is None or not url.startswith("mxc://"):
                            return {}
                        url = url[6:]
                        chat_service_sid = conversation.fetch().chat_service_sid
                        r = requests.get(util.getHomeserverAddress() + '/_matrix/media/r0/download/' + url, headers = util.getMatrixHeaders(), stream=True)
                        file_bytes = r.content
                        hdrs = {"Content-Type": r.headers["content-type"]}
                        r = requests.post('https://mcs.us1.twilio.com/v1/Services/' + chat_service_sid + '/Media', data = file_bytes, auth=twilio_auth, headers = hdrs)
                        media_sid = r.json()["sid"]
                        conversation.messages.create(author=twilio_author, media_sid=media_sid)
            except:
                exc1 = traceback.format_exc()
                try:
                    util.addUserToRoom(room_id, util.getBotMatrixId())
                    util.sendMsgToRoom(room_id, util.getBotMatrixId(), traceback.format_exc())
                except:
                    print(exc1)
                    traceback.print_exc()
        elif room_contains_bot:
            if event["type"] == "m.room.message":
                if event["content"].get("msgtype","") == "m.text":
                    if not util.isMatrixIdAllowed(sender):
                        util.sendMsgToRoom(room_id, util.getBotMatrixId() , 'You are not allowed access to the bridge. ')
                    text = event["content"]["body"]
                    if text == "!config":
                        config_url = util.getAppserviceAddress() + "/config/" + db.updateAuthToken(sender) + "/"
                        util.sendMsgToRoom(room_id, util.getBotMatrixId() , config_url)
            
    return {}

@bp.route('/app/v1/users/<userId>', methods=['GET'])
def matrix_user_exists(userId):
    confirm_auth(request)
    user_data = {
        "username": userId.split(':')[0].removeprefix('@')
    }
    r = requests.post(util.getHomeserverAddress() + '/_matrix/client/r0/register', headers = util.getMatrixHeaders(), json = user_data, params={"user_id":util.getBotMatrixId()})
    if r.status_code != 200:
        abort(500)
    return {}
