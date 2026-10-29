import os, json, glob
import urllib.request, base64

__DEFAULT_CONFIG_PATH = "/etc/patroller/web-ui.json"
__DEFAULT_DATABASE_PATH = "/code/occupancy_data/data.parquet"

UNKNOWN_USER_DISPLAY = "Unknown user"
EMAIL_NOT_AVAILABLE_DISPLAY = "N/A"

def _is_missing_user_value(value):
    return value is None or (isinstance(value, str) and value.strip() == "")

def get_user_display_name(user, user_label=None):
    """Return a safe display name for a patroller user payload."""
    if isinstance(user, dict):
        candidate_keys = [user_label, "name", "username", "user", "login", "ccc-user.name", "email"]
        for key in candidate_keys:
            if key and key in user and not _is_missing_user_value(user.get(key)):
                return str(user[key])
        return UNKNOWN_USER_DISPLAY

    if _is_missing_user_value(user):
        return UNKNOWN_USER_DISPLAY

    return str(user)

def format_user_details(user, user_label=None):
    """Return markdown-safe details for a patroller user payload."""
    if isinstance(user, dict):
        details = []
        keys = list(user.keys())
        if user_label and user_label not in user:
            keys.insert(0, user_label)
        if "email" not in keys:
            keys.append("email")

        for key in keys:
            value = user.get(key, EMAIL_NOT_AVAILABLE_DISPLAY if key == "email" else UNKNOWN_USER_DISPLAY)
            if _is_missing_user_value(value):
                value = EMAIL_NOT_AVAILABLE_DISPLAY if key == "email" else UNKNOWN_USER_DISPLAY
            details.append(f"  * **{key}:** {value}")

        return "\n".join(details)

    return get_user_display_name(user, user_label)

def _load_config( cfg_path):
    if os.path.exists(cfg_path):
        with open(cfg_path,'r') as f:
            cfg = json.load(f)
    else:
        cfg = dict(servers=[])
    
    return cfg

def read_json_webpage(server_url, user=None, password=None, timeout=5):
    request = urllib.request.Request(server_url)
    
    if user and password:
        url_auth = base64.b64encode(('%s:%s' % (user, password)).encode('ascii'))
        
        request.add_header("Authorization", "Basic %s" % url_auth.decode("ascii"))

    with urllib.request.urlopen(request, timeout=timeout) as url:
        return json.loads(url.read().decode())

class Patroller:
    __STATUS_PAGE = "/status"
    __DEVICES_PAGE = "/devices"
    __REQUEST_PAGE = "/request"
    __WAIT_PAGE = "/wait"

    def __init__(self, cfg_path):
        self.cfg = _load_config(cfg_path)
    
    def __len__(self):
        return len(self.cfg['servers'])
    
    def list_servers(self):
        return [s['name'] for s in self.cfg['servers']]

    def __iter__(self):
        cfg = self.cfg 

        gpu_servers = cfg['servers']

        
        user, password = None, None
        if 'http_auth_user' in self.cfg and 'http_auth_pass' in cfg:
            user, password = cfg['http_auth_user'], cfg['http_auth_pass']

        for server_cfg in gpu_servers:
            server_name = server_cfg['name']
            server_url_status = server_cfg['url'] + self.__STATUS_PAGE
            server_url_device = server_cfg['url'] + self.__DEVICES_PAGE
            try:

                server_user, server_password = user, password
                if 'http_auth_user' in server_cfg and 'http_auth_pass' in server_cfg:
                    server_user, server_password = server_cfg['http_auth_user'], server_cfg['http_auth_pass']
                if server_cfg.get('disable_auth'):
                    server_user, server_password = None, None

                gpu_data = read_json_webpage(server_url_status, server_user, server_password)
                gpu_details = read_json_webpage(server_url_device, server_user, server_password)

                yield dict(name=server_name,url=server_url_status, data=gpu_data, devs=gpu_details)
                
            except Exception as ex:
                print('Unable to retrieve server status')

                yield dict(name=server_name,url=server_url_status, data=None, devs=None)


import pandas as pd

class PatrollerHistory:
    def __init__(self, cfg_path, db_path):
        self.patroller = Patroller(cfg_path=cfg_path)
        
        base, ext = os.path.splitext(db_path)
        pattern = f"{base}*.parquet"
        files = glob.glob(pattern)

        if not files:
            raise FileNotFoundError(f"No indexed parquet files found matching {pattern}")

        # Read all parquet files into one DataFrame
        df_list = [pd.read_parquet(f) for f in files]
        self.data = pd.concat(df_list).sort_index()


    def list_servers(self):
        return self.patroller.list_servers()

    def get_history(self):
        return self.data


    def find_server_gpus(self, servers=None):

        df = self.data

        # retrieve all server GPUs    
        server_gpus = dict()
        server_offline = []

        for server_cfg in self.patroller:
            server_name = server_cfg['name']
            gpu_devs = server_cfg['devs']

            # skip if not requested this one
            if servers is not None and server_name not in servers:
                continue

            if server_cfg['data'] is not None:
                # get data from server
                server_gpus[server_name] = [gpu_id for gpu_id,_ in server_cfg['data'].items()]                
            else:            
                # server is unavailable so try to get gpus from histroy
                server_offline.append(server_name)

                # get all gpus for this server
                missing_server_gpus = df[df['server'] == server_name].reset_index()
                missing_server_gpus = missing_server_gpus[['gpu','gpu_index']]

                # if there are multiple gpu with the same gpu_index, then use only the last one (for instance if GPU has been replaced but history contains older entries)
                missing_server_gpus = missing_server_gpus.drop_duplicates(subset='gpu_index', keep='last')

                gpu_index_to_id = dict(zip(missing_server_gpus['gpu_index'],missing_server_gpus['gpu']))

                server_gpus[server_name] = [gpu_index_to_id[i] if i in gpu_index_to_id else 'unknown' for i in range(missing_server_gpus['gpu_index'].max()+1)]
            
            gpu_index_mapping = {gpu_id: gpu_devs[gpu_id]['number'] if gpu_id in gpu_devs else i for i, gpu_id in enumerate(server_gpus[server_name]) }
            server_gpus[server_name] = sorted(server_gpus[server_name], key=lambda x: gpu_index_mapping[x])


        return server_gpus, server_offline

        