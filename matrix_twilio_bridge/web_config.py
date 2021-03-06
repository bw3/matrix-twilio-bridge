import functools

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, abort, jsonify
)

import matrix_twilio_bridge.db
import matrix_twilio_bridge.util as util

db = matrix_twilio_bridge.db.db
bp = Blueprint('web_config', __name__, url_prefix='/config')

@bp.route('/<auth_token>/', methods=['GET'])
def index(auth_token):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    with bp.open_resource('templates/index.html') as file:
        return file.read()

@bp.route('/<auth_token>/twilio-config/', methods=['GET'])
def twilio_config(auth_token):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    try:
        (sid,auth) = db.getTwilioAuthPair(matrix_id)
    except:
        (sid,auth) = ("","")
    return {"sid":sid,"auth":auth}

@bp.route('/<auth_token>/twilio-config/', methods=['POST'])
def twilio_config_save(auth_token):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    json = request.get_json()
    db.setTwilioConfig(matrix_id, json["sid"], json["auth"])
    return {}

@bp.route('/<auth_token>/incoming-numbers/', methods=['GET'])
def incoming_numbers(auth_token):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    numbers = []
    twilio_client = util.getTwilioClient(matrix_id)
    incoming_phone_numbers = twilio_client.incoming_phone_numbers.list(limit=20)
    for record in incoming_phone_numbers:
        numbers += [record.phone_number]
    webhook = twilio_client.conversations.configuration.webhooks().fetch()
    return jsonify(numbers)

@bp.route('/<auth_token>/incoming-numbers/<incoming_number>', methods=['GET'])
def incoming_number(auth_token, incoming_number):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    return util.getIncomingNumberConfig(matrix_id,incoming_number)

@bp.route('/<auth_token>/incoming-numbers/<incoming_number>', methods=['POST'])
def incoming_number_save(auth_token, incoming_number):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    json = request.get_data()
    db.setIncomingNumberConfig(matrix_id, incoming_number, json)
    return {}

