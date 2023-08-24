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
from dotenv import load_dotenv
load_dotenv(".env")

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
... (this Thought/Action/Action Input/Observation can repeat 10 times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {question}
Thought:"""

SERP_KEY = os.getenv('SERPAPI_API_KEY')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Slack API access token
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")


class AI:
    def googleSearch(self, question):
        response = requests.get(f"https://serpapi.com/search?api_key={SERP_KEY}&q={question}")
        data = response.json()
        return data.get('answer_box', {}).get('answer') or data.get('answer_box', {}).get('snippet') or \
            data.get('organic_results', [{}])[0].get('snippet')

    def calculator(self, input):
        return str(sympify(input))

    def __init__(self, template):
        self.template = template
        self.headers = {
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json"
        }
        self.url = "https://api.openai.com/v1/chat/completions"
        self.system_msg = {
            "role": "system",
            "content": "You are a helpful assistant."
        }
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

    def parse_action_input(self, result):
        action_match = re.search(r'Action: (.*?)\n', result)
        action_input_match = re.search(r'Action Input: (.*?)\n', result)
        if action_match and action_input_match:
            action = action_match.group(1).strip()
            action_input = action_input_match.group(1).strip()
            return action, action_input
        else:
            return None, None

    def ask(self, question):
        logging.info(f"Initial request: {question}")
        text = self.template.format(question=question)
        result = self.run_model(text)

        iteration = 1
        while "Action:" in result:
            logging.info(f"Iteration {iteration}: {result}")
            action, action_input = self.parse_action_input(result)
            if action and action in self.tools:
                tool_result = self.tools[action]['execute'](action_input)
                result = result + "\nObservation: " + tool_result
            result = self.run_model(result)
            iteration += 1

        logging.info(f"Final result: {result}")

        # Extract final answer
        final_answer_match = re.search(r'Final Answer:(.*)', result, re.DOTALL)
        if final_answer_match:
            final_answer = final_answer_match.group(1).strip()
            return final_answer
        else:
            return "No final answer found in the response."

    def pretty_print_POST(self, req):
        """
        At this point it is completely built and ready
        to be fired; it is "prepared".

        However pay attention at the formatting used in
        this function because it is programmed to be pretty
        printed and may differ from the actual request.
        """
        return '{}\n{}\r\n{}\r\n\r\n{}'.format(
            '-----------START-----------',
            req.method + ' ' + req.url,
            '\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
            req.body,
        )

    def run_model(self, text):
        data = {
            "model": "gpt-4",
            "messages": [self.system_msg, {"role": "user", "content": text}]
        }
        logging.info(json.dumps(data))
        req = requests.Request('POST', self.url, headers=self.headers, data=json.dumps(data))
        prepared = req.prepare()
        logging.info(self.pretty_print_POST(prepared))
        s = requests.Session()
        response = s.send(prepared)

        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']


# Initialize a new Slack app
app = App(token=SLACK_BOT_TOKEN)


@app.event("app_mention")
def handle_app_mentions(body, say, logger):
    user = body["event"]["user"]
    text = body["event"]["text"].replace('<@U04NDHGEL3U>', '')
    logger.info(f"Received message from {user} with text: {text}")

    try:
        ai = AI(promptTemplate)
        answer = ai.ask(text)

        if answer is None:
            answer = "Sorry, I can't provide an answer at the moment."

        say(answer)
        logger.info(f"Sent response to {user}")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
