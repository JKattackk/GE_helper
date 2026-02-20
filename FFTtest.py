import sys
import requests
import numpy as np
import pandas as pd
import json

# price_request_url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}"
headers = {
    'User-Agent': 'FFT testing @kat6541'
}
sampling_periods = {"5m": 60*5, "1h": 60*60, "6h": 60*60*6, "24h": 60*60*24}

def infill_interp(samples, max_interp):
    """returns the interpolated sample set as well as the average because I dont want to iterate back through all the samples again
    returns [samples, avg]
    """
    avg = 0
    last_valid_sample = -1 # index of last valid sample in set
    first_valid_sample = -1 # index of first valid sample in set
    # finding first valid  sample
    for i in range(len(samples)):
        if samples[i] != None:
            first_valid_sample = i
            break
    print(f"first valid sample {first_valid_sample}")
    if first_valid_sample == -1:
        print("empty dataset provided, cannot interpolate")
        return None
    i = first_valid_sample
    while i < len(samples):
        if samples[i] == None:
            # finding next valid sample
            for j in range(last_valid_sample + 1, last_valid_sample + max_interp):
                #if we reach the end of the set before finding a valid sample
                if j == len(samples):
                    # fill end of set from last item in set
                    for k in range(last_valid_sample+1, j):
                        samples[k] = samples[last_valid_sample]
                        avg += samples[k]
                    i = j-1
                    break
                elif samples[j] is not None:
                    dx = (samples[j] - samples[last_valid_sample]) / (j  - last_valid_sample)
                    print(f"dx is: {dx}")
                    for k in range(last_valid_sample + 1, j):
                        samples[k] = samples[k-1] + dx
                        avg += samples[k] 
                    i = j-1
                    break
                    
        else:
            last_valid_sample = i
            avg += samples[i]
        i = i + 1
    if first_valid_sample != 0:
        # fill start of set from first valid sample
        for k in range(0, first_valid_sample):
            samples[k] = samples[first_valid_sample]
            avg += samples[k]
    print(f"sum is {avg}, and length of set is {len(samples)}")
    avg = avg/len(samples)
    return  [samples, avg]
    
def get_fft(self, item_id, timestep):
    n_samples = 365 # expected number of samples
    max_interp_samples = 16 # maximum gap between samples before function will throw an error instead of interpolating
    if timestep == '5m' or timestep == '1h' or  timestep ==  '6h' or  timestep  ==  '24h':
        price_request_url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}"
        response = requests.get(price_request_url, headers = headers)
        data = json.loads(response.text).get('data')

        sample_count = len(data)
        start_time =  data[0].get("timestamp")
        end_time = data[sample_count - 1].get("timestamp")
        expected_sample_period = sampling_periods.get(timestep)

        # check to make sure all the samples are evenly spaced
        for i in range(sample_count):
            timestamp = data[i].get("timestamp")
            if not timestamp == start_time + i*expected_sample_period:
                print("unexpected spacing in samples")
                return None
            
        # convert into usable timeseries for avgHighPrice
        avgHighPrice_samples  = np.array([data[i].get("avgHighPrice") for i in range(sample_count)])

        # interp null values in avgHighPrice_samples
        avgHighPrice_samples = infill_interp(avgHighPrice_samples, max_interp = max_interp_samples)
        if avgHighPrice_samples == None:
            print("hit maximum interpolation limit, failed to perform FFT")
            return None
        else:
            print("temp")
    else:
        raise ValueError("timestep must be one of '5m', '1h', '6h', or '24h'")


if __name__ == "__main__":
    item_id = '2'
    timeseries =  '5m'
    samples = [None, 2, 3, 4, None, None, None ,None, None, 18]
    [samples, avg] = infill_interp(samples, 10)
    print(samples)
    print(avg)

