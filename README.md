# matrix-twilio-bridge
An alternative to google voice.  
Supports:
- SMS
- MMS (picture messages)
- Group SMS / MMS
- Forward voice calls to other phone numbers. (matrix voip not supported)
- Voicemails as audio attachments and text in your matrix client. 

## Install

Create a system user:

    useradd -r -s /usr/bin/nologin matrix-twilio

Create a directory:

    mkdir /var/lib/matrix-twilio
    chown matrix-twilio /var/lib/matrix-twilio

Checkout:

    cd /var/lib/matrix-twilio
    sudo -u matrix-twilio git clone https://github.com/bw3/matrix-twilio-bridge.git .

Install in virtualenv:

    sudo -u matrix-twilio virtualenv venv
    sudo -u matrix-twilio venv/bin/pip install .

Copy systemd service file, and edit as needed:

    sudo cp systemd/matrix-twilio-bridge.service /etc/systemd/system/

If using a reverse proxy, set it up now. https://gunicorn.org/#deployment

Generate Config Files:

    sudo -u matrix-twilio venv/bin/matrix-twilio-bridge generate-config

Add `/var/lib/matrix-twilio-bridge/registration.yaml` to the list of `app_service_config_files` in `/etc/synapse/homeserver.yaml`

Enable and start the systemd service:

    sudo systemctl enable --now matrix-twilio

## User config
Start a direct message with `@twiliobot`, and type `config`.
This will give you a link to your config page.

### Twilio config
Login to your twilio account. 
Copy your SID and auth token into the bridge config page. 
Go to Conversations > Configure > Global Webhooks
Set Post-Event URL as `<base-url>/twilio/conversation`
Check onMessageAdded, and click Save
Go to Conversations > Configure > Defaults
Unlock Handle Inbound Messages with Conversations
Go to Phone Numbers > Manager Numbers > Active Numbers and click on the phone number you want to set up.
For voice calls, set a webhook for <base-url>/twilio/call
For messaging, set to message service and default conversations service

### Incoming Numbers
#### Forwarding
You can enter up to 10 numbers to forward your calls to. 
Call forwarding is down in parallel, and the first phone to answer will be used.
The check option prevents any automated system from picking up the call. Note that twilio charges extra for the speech option. 
This could be a voicemail system, or a recording saying that the user is out of the service area. 
If you are sure that your phone will never automatically pick up, you can set the check option to None. 
#### Voicemail
You can set custom text to speach message.
### Create SMS Conversation
This will create a room with the numbers you specifiy. This can be a 1 to 1 or group sms conversation. 
### Make Call
This allows you to use one of your forwarding numbers to make a call with the correct caller id. 
### Set Display Name
Set the display name for a given phone number.
