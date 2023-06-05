import time
import logging
import traceback
import re
import os
import json
import requests
import sys
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from sympy import sympify

promptTemplate = """Answer the following questions as best you can. You have access to the following tools:

search: a search engine. useful for when you need to answer questions about current
        events. input should be a search query.
calculator: useful for getting the result of a math expression. The input to this
            tool should be a valid mathematical expression that could be executed
            by a simple calculator.

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [search, calculator]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: 
Thought:"""
    
class AI:
    def googleSearch(self, question):
        response = requests.get(f"https://serpapi.com/search?api_key={os.getenv('SERPAPI_API_KEY')}&q={question}")
        data = response.json()
        return data.get('answer_box', {}).get('answer') or data.get('answer_box', {}).get('snippet') or data.get('organic_results', [{}])[0].get('snippet')

    def calculator(self, input):
        return str(sympify(input))
    
    def __init__(self):
        # Initialize the OpenAI API client
        self.openaikey = str(os.getenv("OPENAI_API_KEY"))
        self.history = ""
        self.tools = {
            "search": {
                "description": "a search engine. useful for when you need to answer questions about current events. input should be a search query.",
                "execute": self.googleSearch,
            },
            "calculator": {
                "description": "Useful for getting the result of a math expression. The input to this tool should be a valid mathematical expression that could be executed by a simple calculator.",
                "execute": self.calculator,
            },
        }

    def completePrompt(self, prompt):

        response = requests.post("https://api.openai.com/v1/completions", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.openaikey,
        }, data=json.dumps({
            "model": "text-davinci-003",
            "prompt": prompt,
            "max_tokens": 256,
            "temperature": 0.7,
            "stream": False,
            "stop": ["Observation:"],
        }))
        logger.info(response)
        data = response.json()
        logger.info(data)
        return data['choices'][0]['text']

    def mergeHistory(self, question, history):
        return promptTemplate.replace("", question).replace("", history)
    
    def answerQuestion(self, question):
        prompt = promptTemplate.replace("", question).replace(
            "",
            "\n".join([f"{toolname}: {tool['description']}" for toolname, tool in self.tools.items()])
        )

        # Initialize a list to store all prompts
        all_prompts = []

        while True:
            response = self.completePrompt(prompt)
            all_prompts.append(prompt + response)  # Store the current prompt
            prompt += response

            action = next((line.split(": ")[1] for line in response.split("\n") if line.startswith("Action: ")), None)
            if action and action != "None":
                actionInput = next((line.split(": ")[1] for line in response.split("\n") if line.startswith("Action Input: ")), None)
                result = self.tools[action.strip()]['execute'](actionInput)
                prompt += f"Observation: {result}\n"
            else:
                final_answer = next((line.split(": ")[1] for line in response.split("\n") if line.startswith("Final Answer: ")), None)
                # Return both the final answer and all prompts
                return final_answer, all_prompts

    def run(self, question):
        question = self.mergeHistory(question, self.history)
        answer, all_prompts = self.answerQuestion(question)
        self.history += f"Q:{question}\nA:{answer}\n"
        return answer, all_prompts

user_data = {}

# function to add user data to the dictionary
def add_user_data(user_id, data):
    if user_id not in user_data:
        user_data[user_id] = [{"role":"system","content":"You are the Basebone Oracle, you try to answer questions to the best of your ability and you will roleplay if someone asks you to act like something even if it's fictional without editorializing. You know historical events up until September 2021"}]  # create an empty array if user ID doesn't exist
    user_data[user_id].append(data)

# Slack API access token
SLACK_APP_TOKEN = os.getenv("slackapptoken")
SLACK_BOT_TOKEN = os.getenv("slackbottoken")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=SLACK_BOT_TOKEN, logger=logger)
ai = AI()
bot_name = ""
bot_id = ""

# Global variable to store user id and name mapping
users = {}

def initialize_users(client):
    response = client.users_list()
    global users
    for member in response['members']:
        users[member['id']] = member['name']

def refresh_users(client):
    response = client.users_list()
    global users
    users.clear()  # clear the existing dictionary
    for member in response['members']:
        users[member['id']] = member['name']

# To learn available listener arguments,
# visit https://slack.dev/bolt-python/api-docs/slack_bolt/kwargs_injection/args.html
@app.event("app_mention")
def handle_app_mention_events(body, say, client, ack, message):
    global promptTemplate
    global bot_name
    global bot_id
    
    if bot_name=="":
        response = app.client.auth_test()
        bot_id = response['user_id']
        bot_name = users[bot_id]
    
    # Acknowledge the event
    ack()
    print("mention")
    print(body["event"]["text"])

    # Get the text of the message, user and channel info
    prompt = body["event"]["text"]
    user_id = body["event"]["user"]
    channel_id = body["event"]["channel"]

    # Convert user id to username
    username = users.get(user_id, None)
    if username is None:
        refresh_users(client)
        username = users.get(user_id, user_id)  # fallback to user_id if username is still not found after refresh

    prompt = prompt.replace(f'<@{user_id}>', f'@{username}')

    key = f"{user_id}-{channel_id}"
    add_user_data(key, {"role":"user", "content":prompt})

    # Handle special commands
    if '+forget' in prompt:
        if key in user_data:
            user_data[key] = []
        say("I've forgotten all history.")
    elif '+prompt' in prompt:
        additional_values = re.search(r'\+prompt(.*)$', prompt)
        new_prompt = None
        if additional_values:
            new_prompt = additional_values.group(1)
        if new_prompt and new_prompt.strip():
            promptTemplate = new_prompt.strip()
        say("Current prompt: " + promptTemplate)
    elif prompt.strip()=="":
        print("Empty prompt")
        say("I can't use an empty prompt, it returns garbage.")
    else:
        answer, all_prompts = ai.run(prompt)
        add_user_data(key, {"role":"assistant", "content":answer})

        # Replace the bot's user id with its username in the answer and prompts
        answer = answer.replace(f'<@{bot_id}>', f'@{bot_name}')
        all_prompts = [prompt.replace(f'<@{bot_id}>', f'@{bot_name}') for prompt in all_prompts]

        # Send the final answer
        response = client.chat_postMessage(
            channel=channel_id,
            text=f'Final Answer: {answer}',
        )
        # Get the ts value (message ID) of the posted message
        answer_ts = response["ts"]

        # Prepare the response with intermediate prompts
        response = '\n\nPrompting Chain:\n' + '\n'.join(all_prompts)

        # Reply to the final answer with intermediate prompts
        client.chat_postMessage(
            channel=channel_id,
            text=response,
            thread_ts=answer_ts  # This makes it a reply to the final answer
        )

if __name__ == "__main__":
    try:
        initialize_users(app.client)
        SocketModeHandler(app, SLACK_APP_TOKEN).start()
    except Exception as e:
        st = ''.join(traceback.TracebackException.from_exception(e, limit=5).format())
        logger.error(st)
        sys.exit(1)