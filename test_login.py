import requests

# Endpoint URL
url = "http://localhost:8000/api/v1/auth/token"

# Form data
data = {
    "username": "test4@example.com",
    "password": "password123"
}

# Headers
headers = {
    "Content-Type": "application/x-www-form-urlencoded"
}

# Send POST request
response = requests.post(url, data=data, headers=headers)

# Print response status code
print(f"Status code: {response.status_code}")

# Print response headers
print("\nResponse headers:")
for header, value in response.headers.items():
    print(f"{header}: {value}")

# Print response body
print("\nResponse body:")
print(response.text)

# If the response is JSON, print it in a prettier format
try:
    json_response = response.json()
    print("\nJSON Response:")
    import json
    print(json.dumps(json_response, indent=4))
except ValueError:
    print("\nResponse is not valid JSON") 