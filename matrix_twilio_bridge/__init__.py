import os,json,urllib,uuid,sqlite3

from flask import (Flask, render_template, request, abort, redirect)
import requests
from twilio.rest import Client as TwilioClient

import matrix_twilio_bridge.db 
import matrix_twilio_bridge.web_config
import matrix_twilio_bridge.matrix_endpoints
import matrix_twilio_bridge.twilio_endpoints

def create_app():
    app = Flask(__name__)

    app.register_blueprint(matrix_twilio_bridge.web_config.bp)
    app.register_blueprint(matrix_twilio_bridge.matrix_endpoints.bp)
    app.register_blueprint(matrix_twilio_bridge.twilio_endpoints.bp)

    @app.route('/transactions/<txnId>', methods=['PUT'])
    def transactions(txnId):
        return matrix_twilio_bridge.matrix_endpoints.matrix_event(txnId)

    @app.route('/users/<userId>', methods=['GET'])
    def users(userId):
        return matrix_twilio_bridge.matrix_endpoints.matrix_user_exists(userId)

    @app.route('/rooms/<roomAlias>', methods=['GET'])
    def rooms(roomAlias):
        return matrix_twilio_bridge.matrix_endpoints.matrix_room_exists(roomAlias)

    return app
