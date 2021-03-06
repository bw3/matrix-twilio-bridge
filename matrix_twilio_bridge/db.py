import sqlite3
import string
import secrets
import threading

class DB:

    def __init__(self):
        self.thread_local = threading.local()
        cur = self._get_conn().cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS room_conversation (matrix_id text, room_id text, conversation_sid text)')
        cur.execute('CREATE TABLE IF NOT EXISTS web_config_auth (matrix_id text UNIQUE, auth_token text UNIQUE)')
        cur.execute('CREATE TABLE IF NOT EXISTS twilio_config (matrix_id text UNIQUE, sid text, auth text)')
        cur.execute('CREATE TABLE IF NOT EXISTS incoming_number (matrix_id text, number text, config text, CONSTRAINT unique_incoming_number UNIQUE(matrix_id, number))')
        self._get_conn().commit()

    def _get_conn(self):
        if not hasattr(self.thread_local, 'conn'):
            self.thread_local.conn = sqlite3.connect('db')
        return self.thread_local.conn

    def getRoomId(self, matrix_id, conversation_sid):
        cur = self._get_conn().cursor()
        cur.execute('SELECT room_id FROM room_conversation WHERE matrix_id=? AND conversation_sid=?',(matrix_id,conversation_sid))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def getConversationSid(self, matrix_id, room_id):
        cur = self._get_conn().cursor()
        cur.execute('SELECT conversation_sid FROM room_conversation WHERE matrix_id=? AND room_id=?',(matrix_id,room_id))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def linkRoomConversation(self, matrix_id, room_id, conversation_sid):
        cur = self._get_conn().cursor()
        cur.execute('INSERT INTO room_conversation VALUES (?,?,?)',(matrix_id, room_id, conversation_sid))
        self._get_conn().commit()

    def updateAuthToken(self, matrix_id):
        alphabet = string.ascii_letters + string.digits
        auth_token = ''.join(secrets.choice(alphabet) for i in range(32))
        cur = self._get_conn().cursor()
        cur.execute('INSERT INTO web_config_auth (matrix_id,auth_token) VALUES(?,?) ON CONFLICT(matrix_id) DO UPDATE SET auth_token=excluded.auth_token', (matrix_id,auth_token))
        cur.execute('SELECT auth_token FROM web_config_auth WHERE matrix_id=?',(matrix_id,))
        result = cur.fetchone()
        self._get_conn().commit()
        return result[0]

    def getMatrixIdFromAuthToken(self, auth_token):
        cur = self._get_conn().cursor()
        cur.execute('SELECT matrix_id FROM web_config_auth WHERE auth_token=?',(auth_token,))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def getTwilioAuthPair(self, matrix_id):
        cur = self._get_conn().cursor()
        cur.execute('SELECT sid,auth FROM twilio_config WHERE matrix_id=?',(matrix_id,))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return (result[0], result[1])

    def getMatrixIdFromSid(self, sid):
        cur = self._get_conn().cursor()
        cur.execute('SELECT matrix_id FROM twilio_config WHERE sid=?',(sid,))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def setTwilioConfig(self, matrix_id, sid, auth):
        cur = self._get_conn().cursor()
        cur.execute('INSERT INTO twilio_config (matrix_id,sid,auth) VALUES(?,?,?) ON CONFLICT(matrix_id) DO UPDATE SET sid=excluded.sid, auth=excluded.auth',(matrix_id,sid,auth))
        self._get_conn().commit()


    def getIncomingNumberConfig(self, matrix_id, number):
        cur = self._get_conn().cursor()
        cur.execute('SELECT config FROM incoming_number WHERE matrix_id=? AND number=?',(matrix_id,number))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def setIncomingNumberConfig(self, matrix_id, number, config):
        cur = self._get_conn().cursor()
        cur.execute('SELECT config FROM incoming_number WHERE matrix_id=? AND number=?',(matrix_id,number))
        result = cur.fetchone()
        if result is None:
            cur.execute('INSERT INTO incoming_number (matrix_id,number,config) VALUES(?,?,?)',(matrix_id,number,config))
        else:
            cur.execute('UPDATE incoming_number SET config=? WHERE matrix_id=? AND number=?', (config,matrix_id,number))
        self._get_conn().commit()

db=DB()
