# lcrpython

To run the bot you will need to add these environment variables

SERPAPI_API_KEY
OPENAI_API_KEY
SLACK_APP_TOKEN
SLACK_BOT_TOKEN

I use a dockerfile to set it up

```
FROM python:3

WORKDIR /opt/app/

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# COPY . .

ENV SERPAPI_API_KEY=
ENV OPENAI_API_KEY=
ENV SLACK_APP_TOKEN=
ENV SLACK_BOT_TOKEN=

CMD [ "python", "./langchain.py" ]
```

docker run -it -d --name=lcri --mount type=bind,source=.,target=/opt/app lcri
