#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Fetches SIEM log data from the Mimecast API and saves to a folder for Sumo Logic data collection"""

import base64
import hashlib
import hmac
import logging
import os
import pickle
import uuid
import time
import datetime
import sys
from os.path import dirname, abspath
from zipfile import ZipFile


import requests


def get_siem_logs():
    app_id = 'fa25890c-fcf9-498e-ba05-0f994adfe510'
    app_key = '67c8deb1-39b2-44a1-8013-9155d7b06fd8'
    
    request_id = str(uuid.uuid4())
    hdr_date = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S") + " UTC"
    uri = '/api/audit/get-siem-logs'
    url = api_base_url + uri
    hmac_sha1 = hmac.new(secret_key.decode("base64"), ':'.join([hdr_date, request_id, uri, app_key]),
                         digestmod=hashlib.sha1).digest()

    sig = base64.encodestring(hmac_sha1).rstrip()

    headers = {
        'Authorization': 'MC ' + access_key + ':' + sig,
        'x-mc-app-id': app_id,
        'x-mc-date': hdr_date,
        'x-mc-req-id': request_id,
        'Content-Type': 'application/json'
    }

    payload = {
        'data': [
            {
                'type': 'MTA',
                'compress': True
            }
        ]
    }

    if os.path.exists(os.path.join(dirname(dirname(abspath(__file__))), 'checkpoint', 'checkpoint_siem')):
        with open(os.path.join(os.path.join(dirname(dirname(abspath(__file__))), 'checkpoint',
                                            'checkpoint_siem')), 'r') as c:
            payload['data'][0]['token'] = c.read()

    try:
        logging.debug('Calling Mimecast: ' + url + ' Request ID: ' + request_id + ' Request Body: ' + str(payload))
        response = requests.post(url=url, data=str(payload), headers=headers, timeout=120)
        logging.debug('Response code: ' + str(response.status_code) + ' Headers: ' + str(response.headers))
        if response.status_code == 429:
            logging.warn('Mimecast API rate limit reached, sleeping for 30 seconds')
            time.sleep(30)
            logging.debug('Calling Mimecast: ' + url + ' Request ID: ' + request_id)
            response = requests.post(url=url, data=str(payload), headers=headers, timeout=120)
        elif response.status_code != 200:
            logging.error('Request to ' + url + ' with , request id: ' + request_id + ' returned with status code: '
                          + str(response.status_code) + ', response body: ' + response.text)
            return False
        elif response.headers['Content-Type'] == 'application/json':
            logging.debug('Response body: ' + response.text)
            logging.info('No more Secure Email Gateway logs to collect.')
            return False

        try:
            #  Retrieve file name
            logging.debug('Retrieving zip file name from response header')
            zip_file_name = response.headers['Content-Disposition'].split('filename="')
            zip_file_name = zip_file_name[1][:-1]
            # Save the file
            logging.debug('Saving zip file to tmp folder: ' + os.path.join(data_dir, zip_file_name))
            with open(os.path.join(data_dir, 'tmp', zip_file_name), 'wb') as z:
                for chunk in response.iter_content():
                    z.write(chunk)

            # Extract the file
            logging.debug('Extracting zip file to Mail Transfer Agent folder: ' + os.path.join(data_dir, 'mta'))
            with ZipFile(os.path.join(data_dir, 'tmp', zip_file_name)) as zip:
                zip.extractall(path=os.path.join(data_dir, 'mta'))
            logging.debug('Extracted zip file to MTA folder: ' + os.path.join(data_dir, 'mta'))

            #Delete zip file
            logging.debug('Removing zip file: ' + os.path.join(data_dir, 'tmp', zip_file_name))
            os.remove(os.path.join(data_dir, 'tmp', zip_file_name))

            logging.debug('Saving checkpoint')
            with open(os.path.join(os.path.join(dirname(dirname(abspath(__file__))), 'checkpoint',
                                                'checkpoint_siem')), 'w') as cs:
                cs.write(response.headers['mc-siem-token'])
            return True
        except Exception, e:
            logging.error('Unexpected error processing log file data. Exception: ' + str(e))
            return False
    except Exception, e:
        logging.error('Unexpected error calling API. Exception: ' + str(e))
        return False


def remove_files(path):
    logging.info('Cleaning up files in: ' +  path)
    try:
        os.chdir(path)
        logging.debug('Directory changed successfully %s' % path)
        for dirpath, dirnames, filenames in os.walk(path):
            for file in filenames:
                curpath = os.path.join(dirpath, file)
                logging.debug('Checking ' + curpath)
                file_modified = datetime.datetime.fromtimestamp(os.path.getmtime(curpath))
                logging.debug('Modified date: ' + str(file_modified))
                if datetime.datetime.now() - file_modified > datetime.timedelta(hours=168):
                    os.remove(curpath)
                    logging.debug('Removed ' + curpath)
                else:
                    logging.debug('Did not remove file: ' + curpath + '. File is not yet 7 days old')
    except Exception, e:
        logging.error('Error cleaning up files. Exception: ' + str(e))


# Start Program
with open(os.path.join(os.path.join(dirname(dirname(abspath(__file__))),
                                    'checkpoint', 'config.txt')), 'rb') as f:
    config = pickle.load(f)

log_dir = os.path.join(os.path.join(dirname(dirname(abspath(__file__))), 'log'))

log_name = 'mta_' + datetime.datetime.utcnow().strftime('%d%m%Y') + '.log'
logging.basicConfig(filename=os.path.join(log_dir, log_name), level=logging.INFO,
                    format='%(levelname)s|%(asctime)s|%(message)s')

account_code = config['account_code']
if len(account_code) < 0:
    logging.error('Log collection aborted. Account code not found, exiting.')
    sys.exit()

logging.info('***** Mimecast Data Collector for Sumo Logic v1.0 *****')
logging.info('Starting siem log collection for ' + account_code)

data_dir = config['data_dir']
if len(data_dir) < 0:
    logging.error('Data directory not set, exiting.')
    sys.exit()
logging.info('Using data directory: ' + data_dir)

access_key = config['access_key']
if len(access_key) < 0:
    logging.error('Access Key not set, exiting.')
    sys.exit()
secret_key = config['secret_key']
if len(secret_key) < 0:
    logging.error('Secret Key not set, exiting.')
    sys.exit()
api_base_url = config['api_base_url']
if len(api_base_url) < 0:
    logging.error('API base URL not set, exiting.')
    sys.exit()

while get_siem_logs() is True:
    logging.info('Collecting Secure Email Gateway logs')

#Clean up data files
remove_files(os.path.join(dirname(dirname(abspath(__file__))), 'log'))
#Clean up log files
remove_files(os.path.join(data_dir, 'mta'))
logging.info('Secure Email Gateway log collection complete')
sys.exit()
