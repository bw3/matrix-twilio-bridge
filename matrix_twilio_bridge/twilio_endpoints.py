import os,json,urllib,uuid,sqlite3,functools

from flask import (
    Flask, render_template, request, abort, redirect, Blueprint, flash, g, redirect, render_template, request, session, url_for, abort
)

import requests
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Dial, VoiceResponse, Say
from twilio.request_validator import RequestValidator

import matrix_twilio_bridge.db
import matrix_twilio_bridge.util as util

db = matrix_twilio_bridge.db.db
config = matrix_twilio_bridge.util.config
bp = Blueprint('twilio', __name__, url_prefix='/twilio')

def validate_twilio_request(f):
    """Validates that incoming requests genuinely originated from Twilio"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        (matrix_id,auth) = db.getMatrixIdAuthFromSid(request.form["AccountSid"])
        validator = RequestValidator(auth)
        request_valid = validator.validate( request.url, request.form, request.headers.get('X-TWILIO-SIGNATURE', ''))
        if request_valid:
            return f(matrix_id, *args, **kwargs)
        else:
            return abort(403)
    return decorated_function

@bp.route('/conversation', methods=['POST'])
@validate_twilio_request
def twilio_msg_recieved(matrix_id):
    author = util.getMatrixId(request.form['Author'])
    conversation_sid = request.form['ConversationSid']
    numbers = util.get_conversation_participants(matrix_id,conversation_sid)
    room_id = util.findRoomId(matrix_id,numbers,conversation_sid)
    if 'Media' in request.form:
        twilio_client = util.getTwilioClient(matrix_id)
        twilio_auth = db.getTwilioAuthPair(matrix_id)
        chat_service_sid = twilio_client.conversations.conversations(conversation_sid).fetch().chat_service_sid
        media = json.loads(request.form['Media'])
        for entry in media:
            media_sid = entry["Sid"]
            content_type = entry["ContentType"]
            filename = entry["Filename"]
            r = requests.get("https://mcs.us1.twilio.com/v1/Services/" + chat_service_sid + "/Media/" + media_sid + "/Content", auth=twilio_auth)
            util.postFileToRoom(room_id, author, content_type, r.content, filename)
    if 'Body' in request.form:
        text = request.form['Body']
        util.sendMsgToRoom(room_id,author, text)
    return {}

@bp.route('/call', methods=['POST'])
@validate_twilio_request
def twilio_call(matrix_id):
    direction = request.values['Direction']
    to_number = request.values['To']
    from_number = request.values['From']
    call_status = request.values["CallStatus"]
    json_config = util.getIncomingNumberConfig(matrix_id, to_number)
    response = VoiceResponse()
    if direction == 'inbound':
        if json_config["hunt_enabled"]:
            dial = Dial(action = util.adjustUrl(request.url,"voicemail"),timeout=json_config["hunt_timeout"],answerOnBridge=True)
            for pair in json_config["hunt_numbers"]:
                dial.number(pair[0], send_digits=pair[1])
            response.append(dial)
        else:
            return twilio_voicemail()
    return str(response)

@bp.route('/voicemail', methods=['POST'])
@validate_twilio_request
def twilio_voicemail(matrix_id):
    twilio_client = util.getTwilioClient(matrix_id)
    call = twilio_client.calls(request.values["CallSid"]).fetch()
    to_number = call.to
    from_number = call.from_
    try:
        call_status = request.values["DialCallStatus"]
    except:
        call_status = request.values["CallStatus"]
    json_config = util.getIncomingNumberConfig(matrix_id, to_number)
    response = VoiceResponse()
    if json_config["voicemail_enabled"] and call_status != "completed":
        room_id = util.findRoomId(matrix_id,[to_number] + [from_number])
        author = util.getBotMatrixId()
        util.sendMsgToRoom(room_id,author, "missed call")
        response.say(json_config["voicemail_tts"])
        kwargs = {
            "timeout":                  json_config["voicemail_timeout"], 
            "transcribe":               json_config["voicemail_transcribe"], 
            "playBeep":                 True, 
            "recordingStatusCallback":  util.adjustUrl(request.url,"voicemail_recording"),
            "action":                   util.adjustUrl(request.url,"reject"),
            "transcribeCallback":       util.adjustUrl(request.url,"voicemail_transcription")
        }
        response.record(**kwargs)
    else:
        response.reject()
    return str(response)

@bp.route('/voicemail_recording', methods=['POST'])
@validate_twilio_request
def twilio_voicemail_recording(matrix_id):
    twilio_client = util.getTwilioClient(matrix_id)
    call = twilio_client.calls(request.values["CallSid"]).fetch()
    to_number = call.to
    from_number = call.from_
    json_config = util.getIncomingNumberConfig(matrix_id, to_number)
    recording_url = request.values["RecordingUrl"]
    r = requests.get(recording_url+".mp3")
    room_id = util.findRoomId(matrix_id,[to_number] + [from_number])
    author = util.getBotMatrixId()
    util.postFileToRoom(room_id, author, r.headers["content-type"], r.content, "voicemail.mp3")
    return {}

@bp.route('/voicemail_transcription', methods=['POST'])
@validate_twilio_request
def twilio_voicemail_transcription(matrix_id):
    twilio_client = util.getTwilioClient(matrix_id)
    call = twilio_client.calls(request.values["CallSid"]).fetch()
    to_number = call.to
    from_number = call.from_
    json_config = util.getIncomingNumberConfig(matrix_id, to_number)
    recording_url = request.values["RecordingUrl"]
    r = requests.get(recording_url+".mp3")
    room_id = util.findRoomId(matrix_id,[to_number] + [from_number])
    author = util.getBotMatrixId()
    util.sendMsgToRoom(room_id,author, request.values["TranscriptionText"])
    return {}


@bp.route('/reject', methods=['POST'])
def twilio_reject():
    response = VoiceResponse()
    response.reject()
    return str(response)
