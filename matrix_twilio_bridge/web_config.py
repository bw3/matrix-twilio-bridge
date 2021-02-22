import functools

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, abort
)

import matrix_twilio_bridge.db

db = matrix_twilio_bridge.db.db
bp = Blueprint('web_config', __name__, url_prefix='/config')

@bp.route('/<auth_token>/', methods=['GET'])
def index(auth_token):
    matrix_id = db.getMatrixIdFromAuthToken(auth_token)
    if matrix_id is None:
        abort(403)
    with bp.open_resource('templates/index.html') as file:
        return file.read()
