import os,json,urllib,uuid,sqlite3,functools,traceback

from flask import (
    Flask, render_template, request, abort, redirect, Blueprint, flash, g, redirect, render_template, request, session, url_for, abort
)

import requests
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Dial, VoiceResponse, Say, Gather
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
        twilio_signature = ''
        for (hdr,val) in request.headers.items():
            if hdr.lower() == 'x-twilio-signature':
                twilio_signature = val
        url = util.getAppserviceAddress().rstrip('/') + urllib.parse.urlparse(request.url).path
        request_valid = validator.validate( url, request.form, twilio_signature)
        if request_valid and util.isMatrixIdAllowed(matrix_id):
            try:
                return f(matrix_id, *args, **kwargs)
            except:
                error_msg = str(request) + '\n' + str(request.headers) + '\n' + traceback.format_exc()
                util.sendNoticeToRoom(db.getBotRoom(matrix_id), util.getBotMatrixId(), error_msg)
                abort(500)
        else:
            return abort(403)
    return decorated_function

@bp.route('/conversation', methods=['POST'])
@validate_twilio_request
def twilio_msg_recieved(matrix_id):
    util.recv_twilio_msg(matrix_id,request.form['ConversationSid'],request.form['MessageSid'])
    return {}

@bp.route('/call', methods=['POST'])
@validate_twilio_request
def twilio_call(matrix_id):
    twilio_client = util.getTwilioClient(matrix_id)
    direction = request.values['Direction']
    to_number = request.values['To']
    from_number = request.values['From']
    call_status = request.values["CallStatus"]
    forwarded_from = request.values.get("ForwardedFrom", None)
    json_config = util.getIncomingNumberConfig(matrix_id, to_number)
    url = util.getAppserviceAddress().rstrip('/') + urllib.parse.urlparse(request.url).path
    response = VoiceResponse()
    if direction == 'inbound':
        from_hunt_number = False
        for entry in json_config["hunt_numbers"]:
            if entry[0] == from_number or entry[0] == forwarded_from:
                from_hunt_number = True
                break

        loop_detected = False
        if from_hunt_number:
            if len(twilio_client.calls.list(status="ringing",limit=2)) > 1:
                loop_detected = True
            if len(twilio_client.calls.list(status="queued",limit=2)) > 0:
                loop_detected = True
            if len(twilio_client.calls.list(status="in-progress",limit=2)) > 0:
                loop_detected = True

        if json_config["hunt_enabled"] and not from_hunt_number:
            dial = Dial(action = util.adjustUrl(url,"voicemail"),timeout=json_config["hunt_timeout"],answerOnBridge=True)
            for pair in json_config["hunt_numbers"]:
                if pair[2] == "":
                    url = util.getAppserviceAddress() + "/twilio/check-accept"
                elif pair[2] == "key":
                    url = util.getAppserviceAddress() + "/twilio/check-key"
                elif pair[2] == "speech":
                    url = util.getAppserviceAddress() + "/twilio/check-speech"
                dial.number(pair[0], send_digits=pair[1], url=url)
            response.append(dial)
        elif not loop_detected:
            return twilio_voicemail()
        else:
            response.reject()
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
    url = util.getAppserviceAddress().rstrip('/') + urllib.parse.urlparse(request.url).path
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
            "recordingStatusCallback":  util.adjustUrl(url,"voicemail_recording"),
            "action":                   util.adjustUrl(url,"reject"),
            "transcribeCallback":       util.adjustUrl(url,"voicemail_transcription")
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
    util.sendMsgToRoom(room_id,author, request.values.get("TranscriptionText","(No transcription available)"))
    return {}

@bp.route('/reject', methods=['POST'])
def twilio_reject():
    response = VoiceResponse()
    response.reject()
    return str(response)

def check_human_key(url):
    response = VoiceResponse()
    gather = Gather(input='dtmf', timeout=10, numDigits=1, action=url, finishOnKey='')
    gather.say('To accept this call, press any key. '*3)
    response.append(gather)
    response.hangup()
    return str(response)

def check_human_speech(url):
    response = VoiceResponse()
    gather = Gather(input='speech dtmf', timeout=10, speechTimeout=1, numDigits=1, action=url, hints='accept', finishOnKey='')
    gather.say('To accept this call, press any key or say accept. '*3)
    response.append(gather)
    response.hangup()
    return str(response)


@bp.route('/check-key-dial-number/<number>', methods=['POST'])
def twilio_check_key_dial_number(number):
    return check_human_key(util.getAppserviceAddress() + "/twilio/dial-number/" + number)

@bp.route('/check-speech-dial-number/<number>', methods=['POST'])
def twilio_check_speech_dial_number(number):
    return check_human_speech(util.getAppserviceAddress() + "/twilio/dial-number/" + number)

@bp.route('/check-key', methods=['POST'])
def twilio_check_key():
    return check_human_key(util.getAppserviceAddress() + "/twilio/check-accept")

@bp.route('/check-speech', methods=['POST'])
def twilio_check_speech():
    return check_human_speech(util.getAppserviceAddress() + "/twilio/check-accept")

@bp.route('/check-accept', methods=['POST'])
def twilio_check_accept():
    response = VoiceResponse()
    if not "accept" in request.values.get("SpeechResult","accept").lower():
        response.hangup()
    return str(response)

@bp.route('/dial-number/<number>', methods=['POST'])
def twilio_dial_number(number):
    if not "accept" in request.values.get("SpeechResult","accept").lower():
        response = VoiceResponse()
        response.reject()
        return str(response)
    response = VoiceResponse()
    dial = Dial(answerOnBridge=True)
    dial.number(number)
    response.append(dial)
    response.hangup()
    return str(response)
