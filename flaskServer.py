from flask import Flask, jsonify, request
import syncManager

from dotenv import load_dotenv
import os

load_dotenv()

activationKey = os.environ.get('ACTIVATION_KEY')

app = Flask(__name__)

@app.route('/', methods=['GET'])
def hello_world():
    return 'Hello, World!'

@app.route('/', methods=['POST'])
def hello_world_post():
    req = request.get_json()
    res = {
        'message': 'Hello, World!',
        'data': req
    }
    return jsonify(res), 200

@app.route('/sync', methods=['POST'])
def sync_naver_reservation():
    req = request.get_json()
    targetDateStr = req['targetDateStr']
    targetRoom = req['targetRoom']
    if checkActivationKey(req) == False:
        res = {
            'message': 'Invalid Access Key',
            'data': req
        }
        return jsonify(res), 401
    print(targetDateStr, targetRoom)
    syncManager.SyncNaver(targetDateStr, targetRoom)
    res = {
        'message': 'Sync Naver Reservation',
        'data': req
    }
    return jsonify(res), 200

@app.route('/sync', methods=['GET'])
def get_naver_reservation():
    req = request.get_json()
    if checkActivationKey(req) == False:
        res = {
            'message': 'Invalid Access Key',
            'data': {}
        }
        return jsonify(res), 401
    notCanceledBookingList, allBookingList = syncManager.getNaverReservation(1)
    res = {
        'message': 'Sync Naver Reservation',
        'notCanceledBookingList': notCanceledBookingList,
        'allBookingList': allBookingList
    }
    return jsonify(res), 200

def checkActivationKey(req):
    if 'activationKey' not in req:
        return False
    if activationKey != req['activationKey']:
        return False
    return True

if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)