import sqlite3
import string
import secrets

class DB:

    def __init__(self):
        self.conn = sqlite3.connect('db')
        cur = self.conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS room_conversation (matrix_id text, room_id text, conversation_sid text)')
        cur.execute('CREATE TABLE IF NOT EXISTS web_config_auth (matrix_id text UNIQUE, auth_token text UNIQUE)')
        self.conn.commit()

    def getRoomId(self, matrix_id, conversation_sid):
        cur = self.conn.cursor()
        cur.execute('SELECT room_id FROM room_conversation WHERE matrix_id=? AND conversation_sid=?',(matrix_id,conversation_sid))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def getConversationSid(self, matrix_id, room_id):
        cur = self.conn.cursor()
        cur.execute('SELECT conversation_sid FROM room_conversation WHERE matrix_id=? AND room_id=?',(matrix_id,room_id))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]

    def linkRoomConversation(self, matrix_id, room_id, conversation_sid):
        cur = self.conn.cursor()
        cur.execute('INSERT INTO room_conversation VALUES (?,?,?)',(matrix_id, room_id, conversation_sid))
        self.conn.commit()

    def updateAuthToken(self, matrix_id):
        alphabet = string.ascii_letters + string.digits
        auth_token = ''.join(secrets.choice(alphabet) for i in range(32))
        cur = self.conn.cursor()
        cur.execute('INSERT INTO web_config_auth (matrix_id,auth_token) VALUES(?,?) ON CONFLICT(matrix_id) DO UPDATE SET auth_token=excluded.auth_token', (matrix_id,auth_token))
        cur.execute('SELECT auth_token FROM web_config_auth WHERE matrix_id=?',(matrix_id,))
        result = cur.fetchone()
        self.conn.commit()
        return result[0]

    def getMatrixIdFromAuthToken(self, auth_token):
        cur = self.conn.cursor()
        cur.execute('SELECT matrix_id FROM web_config_auth WHERE auth_token=?',(auth_token,))
        result = cur.fetchone()
        if result is None:
            return result
        else:
            return result[0]


    
        

