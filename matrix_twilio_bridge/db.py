import sqlite3

class DB:

    def __init__(self):
        self.conn = sqlite3.connect('db')
        cur = self.conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS room_conversation (matrix_id text, room_id text, conversation_sid text)')
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

