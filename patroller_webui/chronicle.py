import sys, os, time, glob
from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH, get_user_display_name
import pandas as pd

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

def retrieve_server_occupancy(pattroler):

    occupancy_data = dict()

    for server_cfg in pattroler:
        server_name = server_cfg['name']
        gpu_data = server_cfg['data']
        gpu_devs = server_cfg['devs']

        if gpu_data is not None:
            for gpu_id,gpu_info in gpu_data.items():

                if "user" in gpu_info['claim'] and gpu_info['claim']['user'] is not None:
                    gpu_index = gpu_devs[gpu_id]['number']
                    claim_age = gpu_info['claim']['age']
                    claim_user = gpu_info['claim']['user']
                    
                    if server_name not in occupancy_data:
                        occupancy_data[server_name] = dict()

                    occupancy_data[server_name][gpu_id] = dict(user=claim_user, age=claim_age, gpu_index=gpu_index)

    return occupancy_data


def userdata_to_log(user, user_label):
    return get_user_display_name(user, user_label)


def get_latest_parquet_path():
    """Find latest indexed parquet file and return its path and index."""
    base, ext = os.path.splitext(__DEFAULT_DATABASE_PATH)  # /code/occupancy_data/data , .parquet
    pattern = f"{base}_*.parquet"
    files = glob.glob(pattern)

    if not files:
        return f"{base}_0.parquet", 0

    indexed_files = []
    for f in files:
        try:
            idx = int(os.path.splitext(f)[0].split("_")[-1])
            indexed_files.append((idx, f))
        except ValueError:
            pass

    if not indexed_files:
        return f"{base}_0.parquet", 0

    latest_idx, latest_file = max(indexed_files, key=lambda x: x[0])
    return latest_file, latest_idx


def chronicle_patroller():
    pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)

    parquet_path, file_index = get_latest_parquet_path()

    while True:
        try:
            # Monitor specific queries (implement this function later)
            occupancy_data = retrieve_server_occupancy(pattroler)
            
            # Convert occupancy_data dict to pandas format with 'timestamp', 'server', 'gpu', 'user', 'age' columns:
            time_now = time.time()
            occupancy_list = []
            for server, gpu_data in occupancy_data.items():
                for gpu, info in gpu_data.items():
                    occupancy_list.append({
                        'timestamp': time_now,
                        'server': server,
                        'gpu': gpu,                        
                        'gpu_index': info['gpu_index'],
                        'user': userdata_to_log(info['user'], pattroler.cfg['user_label']),
                        'age': info['age']
                    })

            occupancy_df = pd.DataFrame(occupancy_list,  columns=['timestamp', 'server', 'gpu', 'gpu_index', 'user','age'])
            occupancy_df.set_index('timestamp', inplace=True)

            # Check file size before writing
            if os.path.exists(parquet_path) and os.path.getsize(parquet_path) > MAX_FILE_SIZE:
                file_index += 1
                base, ext = os.path.splitext(__DEFAULT_DATABASE_PATH)
                parquet_path = f"{base}_{file_index}.parquet"
            
            occupancy_df.to_parquet(
                parquet_path,
                index=True,
                engine='fastparquet',
                append=os.path.exists(parquet_path) and os.path.getsize(parquet_path) > 0
            )

        except Exception as ex:
            print('Error while retrieve_server_occupancy and writing to parquet', ex)
            import traceback
            traceback.print_exception(type(ex), ex, ex.__traceback__)

        # Sleep for 1 minute before monitoring again        
        time.sleep(60)



if __name__ == "__main__":
    chronicle_patroller()
