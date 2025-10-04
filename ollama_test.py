import requests
OLLAMA_API = "http://AA-248:11434/api/chat"
HEADERS = {"Content-Type": "application/json"}
# MODEL = "deepseek-r1"
MODEL = "llama3.2"
# MODEL = "qwen2.5vl"

messages = [
    {"role": "user", "content": "Tell me a random dad joke."}
]

payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
    }

response = requests.post(OLLAMA_API, json=payload, headers=HEADERS)
print(response.json()['message']['content'])