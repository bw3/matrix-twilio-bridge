import functools, traceback, json

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, abort, jsonify, make_response
)

import matrix_twilio_bridge.db
import matrix_twilio_bridge.util as util

db = matrix_twilio_bridge.db.db
bp = Blueprint('web_config', __name__, url_prefix='/config')

def validate_request(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        matrix_id = db.getMatrixIdFromAuthToken(kwargs['auth_token'])
        if matrix_id is None:
            abort(403)
        if not util.isMatrixIdAllowed(matrix_id):
            abort(403)
        del kwargs['auth_token']
        return f(matrix_id, *args, **kwargs)
    return decorated_function


@bp.route('/<auth_token>/', methods=['GET'])
@validate_request
def index(matrix_id):
    with bp.open_resource('templates/index.html') as file:
        return file.read()

@bp.route('/<auth_token>/twilio-config/', methods=['GET'])
@validate_request
def twilio_config(matrix_id):
    try:
        (sid,auth) = db.getTwilioAuthPair(matrix_id)
    except:
        (sid,auth) = ("","")
    return {"sid":sid,"auth":auth}

@bp.route('/<auth_token>/twilio-config/', methods=['POST'])
@validate_request
def twilio_config_save(matrix_id):
    json = request.get_json()
    db.setTwilioConfig(matrix_id, json["sid"], json["auth"])
    return {}

@bp.route('/<auth_token>/incoming-numbers/', methods=['GET'])
@validate_request
def incoming_numbers(matrix_id):
    numbers = []
    twilio_client = util.getTwilioClient(matrix_id)
    incoming_phone_numbers = twilio_client.incoming_phone_numbers.list(limit=20)
    for record in incoming_phone_numbers:
        numbers += [record.phone_number]
    webhook = twilio_client.conversations.configuration.webhooks().fetch()
    return jsonify(numbers)

@bp.route('/<auth_token>/incoming-numbers/<incoming_number>', methods=['GET'])
@validate_request
def incoming_number(matrix_id, incoming_number):
    return util.getIncomingNumberConfig(matrix_id,incoming_number)

@bp.route('/<auth_token>/incoming-numbers/<incoming_number>', methods=['POST'])
@validate_request
def incoming_number_save(matrix_id, incoming_number):
    json = request.get_data()
    db.setIncomingNumberConfig(matrix_id, incoming_number, json)
    return {}

@bp.route('/<auth_token>/create-conversation', methods=['POST'])
@validate_request
def create_conversation(matrix_id):
    twilio_client = util.getTwilioClient(matrix_id)
    json = request.get_json()
    from_number = json["from"]
    to_numbers = json["to"]
    numbers = to_numbers + [from_number]
    util.createRoom(matrix_id,numbers)
    return {}

@bp.route('/<auth_token>/forwarding-numbers/', methods=['GET'])
@validate_request
def forwarding_numbers(matrix_id):
    config_pairs = db.getIncomingNumberConfigs(matrix_id)
    resp = {}
    for config_pair in config_pairs:
        number = config_pair[0]
        config = json.loads(config_pair[1])
        resp[number] = config["hunt_numbers"]
    return resp;

@bp.route('/<auth_token>/make-call', methods=['POST'])
@validate_request
def make_call(matrix_id):
    json = request.get_json()
    twilio_client = util.getTwilioClient(matrix_id)
    if json['from'][2] == "":
        url = util.getAppserviceAddress() + '/twilio/dial-number/' + json['to']
    elif json['from'][2] == "key":
        url = util.getAppserviceAddress() + '/twilio/check-key-dial-number/' + json['to']
    elif json['from'][2] == "speech":
        url = util.getAppserviceAddress() + '/twilio/check-speech-dial-number/' + json['to']
    twilio_client.calls.create( to=json['from'][0], send_digits=json['from'][1], from_=json['caller_id'], url=url)
    return {}
