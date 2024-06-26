# WebUI for Patroller

A web display console for all the data colelted by patrollers. 

## Dependency

```bash
streamlit==1.36.0
fastparquet 
```

## Usage

```
streamlit run patroller_webui/main.py [CONFIG.json]
```

## Config file

```json
{
  "http_auth_user": "username",
  "http_auth_pass": "password",
  "servers": [
    {"name": "my_server_1", "url": "https://my_server_1.domain.com/status"},
    {"name": "my_server_2", "url": "https://my_server_2.domain.com/status"},
    {"name": "my_server_3", "url": "https://my_server_2.domain.com/status"},
  ],
  "user_label": "my-docker-label-for-username"
}
```