import os
import re
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient  # Import WebClient here
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from jira import JIRA, JIRAError


# Load environment variables
load_dotenv()

# Initializes your app with your bot token
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Initializes the Jira client
jira_options = {'server': os.environ.get("JIRA_SERVER")}
jira_client = JIRA(options=jira_options, basic_auth=(os.environ.get("JIRA_USER_EMAIL"), os.environ.get("JIRA_API_TOKEN")))

@app.message(":wave:")
def say_hello(message, say):
    user = message['user']
    say(f"Hi there, <@{user}>!")

@app.event("app_mention")
def handle_app_mention_events(body, logger):
    logger.info(body)

@app.event("message")
def handle_message_events(body, logger):
    logger.info(body)

@app.command("/request")
def handle_command(ack, body, client, logger):
    try:
        ack()
        channel_id = body['channel_id']  # Capture the channel ID
        trigger_id = body['trigger_id']
        open_modal(client, trigger_id, channel_id, logger) # Listens to incoming commands via "request"
        logger.info(body)
    except Exception as e:
        logger.error(f"Error handling slash command: {e}")

def open_modal(client: WebClient, trigger_id: str, channel_id: str,logger):
    try:
        # Define the modal
        modal = {
            "type": "modal",
            "callback_id": "modal-identifier",
            "title": {"type": "plain_text", "text": "Adhoc Request"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "private_metadata": str(channel_id),  # Add channel_id to the modal's private metadata
            "blocks": [
                {
                    "type": "input",
                    "block_id": "request_block",
                    "element": {"type": "plain_text_input", "action_id": "request"},
                    "label": {"type": "plain_text", "text": "Request"}
                },
                {
                    "type": "input",
                    "block_id": "urgency_block",
                    "element": {
                        "type": "static_select",
                        "action_id": "urgency",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "P1 - High urgency"},
                                "value": "P1"
                            },
                            {
                                "text": {"type": "plain_text", "text": "P2 - Medium urgency"},
                                "value": "P2"
                            },
                            {
                                "text": {"type": "plain_text", "text": "P3 - Low urgency"},
                                "value": "P3"
                            }
                        ]
                    },
                    "label": {"type": "plain_text", "text": "Urgency"}
                },
                {
                    "type": "input",
                    "block_id": "impact_block",
                    "element": {"type": "plain_text_input", "multiline": True, "action_id": "business_impact"},
                    "label": {"type": "plain_text", "text": "Business Impact"}
                }
            ]
        }
        client.views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        logger.error(f"Error opening modal: {e}")

request_counter = 0

def get_slack_user_info(user_id, client, logger):
    try:
        response = client.users_info(user=user_id)
        if response["ok"]:
            user_info = response["user"]
            # Extract the necessary details, e.g., user's real name or email
            user_name = user_info.get("real_name") or user_info.get("name")
            return user_name
    except SlackApiError as e:
        logger.error(f"Error fetching user info from Slack: {e}")
        return None

def get_slack_user_email(user_id, client, logger):
    try:
        response = client.users_info(user=user_id)
        if response["ok"]:
            user_info = response["user"]
            return user_info.get("profile", {}).get("email")
    except SlackApiError as e:
        # Assuming you have a logger set up
        logger.error(f"Error fetching user info from Slack: {e}")
        return None

def map_email_to_jira_username(email):
    # Split the email at '@' and then split the first part at '.'
    parts = email.split('@')[0].split('.')
    # Concatenate the first name and last name with a period between them
    jira_username = parts[0] + '.' + parts[1]
    return jira_username


@app.view("modal-identifier")
def handle_modal_submission(ack, body, client, logger):
    global request_counter
    ack()

    channel_id = body['view']['private_metadata']  # Retrieve the channel ID from private metadata

    # Extract submission data
    user_id = body["user"]["id"]
    slack_user_name = get_slack_user_info(user_id, client, logger)
    slack_user_email = get_slack_user_email(user_id, client, logger)
    jira_username = map_email_to_jira_username(slack_user_email)
    submission = body['view']['state']['values']
    request_text = submission['request_block']['request']['value']
    urgency = submission['urgency_block']['urgency']['selected_option']['value']
    business_impact = submission['impact_block']['business_impact']['value']
    user_id = body["user"]["id"]

    # Generate and format request ID
    request_counter = (request_counter + 1) % 1000
    request_id = f"{request_counter:03}"

    # Post the summary message to the same channel where the command was issued
    try:
        client.chat_postMessage(
            channel=channel_id,  # Use the captured channel ID
            text=f"Request ID: {request_id}\nUser: <@{user_id}>\nRequest: {request_text}\nUrgency: {urgency}\nBusiness Impact: {business_impact}"
        )
    except SlackApiError as e:
        logger.error(f"Error posting message: {e}")

    # Create a Jira issue
    issue_dict = {
        'project': {'key': 'SAK'},
        'summary': f"New Request from Slack: {request_text}",
        'description': f"Urgency: {urgency}\nBusiness Impact: {business_impact}",
        'reporter': {'name': jira_username},
        'customfield_10032': {'value': urgency} if urgency else None,
        'customfield_10033': business_impact,
        'customfield_10036': request_id,
        'issuetype': {'name': 'Task'},
    }
    try:
        new_issue = jira_client.create_issue(fields=issue_dict)
        # Handle success (e.g., log the issue creation, inform the user, etc.)
    except JIRAError as e:
        logger.error(f"Error creating Jira issue: {e}")
        # Handle the error (e.g., send a message back to the user)


@app.command("/request")
def handle_command(ack, body, client, logger):
    try:
        ack()
        channel_id = body['channel_id']  # Capture the channel ID
        trigger_id = body['trigger_id']
        open_modal(client, trigger_id, channel_id, logger) # Listens to incoming commands via "request"
        logger.info(body)
    except Exception as e:
        logger.error(f"Error handling slash command: {e}")

# Start the app in Socket Mode
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()