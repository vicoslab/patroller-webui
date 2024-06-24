import sys, os, time

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH
import pandas as pd

def retrieve_server_occupancy(pattroler):

    occupancy_data = dict()

    for server_cfg in pattroler:
        server_name = server_cfg['name']
        gpu_data = server_cfg['data']
        
        if gpu_data is not None:
            for gpu_id,gpu_info in gpu_data.items():

                if "user" in gpu_info['claim']:
                    claim_age = gpu_info['claim']['age']
                    claim_user = gpu_info['claim']['user']
                    
                    if server_name not in occupancy_data:
                        occupancy_data[server_name] = dict()

                    occupancy_data[server_name][gpu_id] = dict(user=claim_user, age=claim_age)

    return occupancy_data

def chronicle_patroller():
    pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)

    while True:
        # Monitor specific queries (implement this function later)
        occupancy_data = retrieve_server_occupancy(pattroler)
        print(occupancy_data)
        
        # Convert occupancy_data dict to pandas format with 'timestamp', 'server', 'gpu', 'user', 'age' columns:
        time_now = time.time()
        occupancy_list = []
        for server, gpu_data in occupancy_data.items():
            for gpu, info in gpu_data.items():
                occupancy_list.append({
                    'timestamp': time_now,
                    'server': server,
                    'gpu': gpu,
                    'user': info['user'],
                    'age': info['age']
                })

        occupancy_df = pd.DataFrame(occupancy_list)
        occupancy_df.set_index('timestamp', inplace=True)

        
        # Save results using fastparquet 
        occupancy_df.to_parquet(__DEFAULT_DATABASE_PATH, index=True, engine='fastparquet', append=os.path.exists(__DEFAULT_DATABASE_PATH))
        
        # Sleep for 1 minute before monitoring again        
        time.sleep(60)



if __name__ == "__main__":
    chronicle_patroller()
