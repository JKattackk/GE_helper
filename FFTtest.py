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
        if samples[i] != None and samples[i] != 'null':
            first_valid_sample = i
            break
    print(f"first valid sample {first_valid_sample}")
    if first_valid_sample == -1:
        print("empty dataset provided, cannot interpolate")
        return None
    i = first_valid_sample
    while i < len(samples):
        if samples[i] == None or samples[i] == 'null':
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
                elif samples[j] is not None and samples[j] != 'null':
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
    
def resample(dataset, max_interp, sampling_period):
    """
    takes list of dicts
    [{'timestamp', . . . }]
    first entry should  be timestamps
    rest are data  samples at that timestamp
    """
    # should I try to do it all in one pass? Probably more efficient
    # would be easier to infill the missing samples with None values and then interpolate each set individually
    # if I feel like it I can write the other version later and compare performance

    if sampling_period == 0:
        print("sampling period can not be zero.")
        return None
    try: 
        last_time = dataset[0].get('timestamp') - sampling_period
    except: 
        print("invalid dataset provided, could not find timestamp")
        return None
    count = 0
    new_dataset = []
    null_sample = dict.fromkeys(dataset[0])

    # check for missing samples and infill with None values
    added_samples = 0
    for i in range(len(dataset)):
        try:
            timestamp = dataset[i].get('timestamp')
        except: 
            print("invalid dataset provided, could not find timestamp")
            return None
        # check if timestamp is the next expected timestamp
        if timestamp != last_time  + sampling_period:
            # if timestamp is not a multiple of the sampling period from start time, exit
            # I hope this does not happen because otherwise I have to handle it later
            if (timestamp - last_time) % sampling_period != 0:
                print("uneven spacing in samples, cannot resample")
                return None
            else:
                # see how many samples are missing
                missing_samples = int((timestamp - dataset[i-1].get("timestamp"))/sampling_period) - 1
                if missing_samples > max_interp:
                    print("too many missing samples, cannot resample")
                    return None
                else:
                    # add missing samples with None values
                    for j in range(missing_samples):
                        null_sample["timestamp"] = last_time + sampling_period
                        # idk if this is the best way to do this
                        new_dataset.append(dict(null_sample))
                        last_time = last_time + sampling_period
                        added_samples += 1
                    new_dataset.append(dict(dataset[i]))
                    last_time = dataset[i].get("timestamp")
        else:
            new_dataset.append(dict(dataset[i]))
            last_time = dataset[i].get("timestamp")

    # temporary check to see if it did things right
    last_time = new_dataset[0].get("timestamp") - sampling_period
    for i in range(len(new_dataset)):
            timestamp = new_dataset[i].get("timestamp")
            if not timestamp == last_time + sampling_period:
                print("unexpected spacing in new dataset")
                return None
            last_time = new_dataset[i].get("timestamp")
    print("seems good to me")





def get_fft(item_id, timestep):
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
        # THIS HAPPENS MORE OFTEN THAN I THOUGHT
        # THIS CHECK SHOULD BE ADDED TO THE INFILL/RESAMPLE FUNCTION INSTEAD AND DEALT WITH
        new_dataset = resample(data, 10, expected_sample_period)
        print(new_dataset)
        
        # convert into usable timeseries for avgHighPrice
        avgHighPrice_samples  = np.array([data[i].get("avgHighPrice") for i in range(sample_count)])

        # this is where I would check for the best set of 256 samples to use if I decide to add  that
        if len(avgHighPrice_samples) < 256:
            print("less than 256 samples given")
            return None
        else:
            avgHighPrice_samples = avgHighPrice_samples[-256:]
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
    item_id = '95'
    timeseries =  '5m'
    get_fft(item_id, timeseries)

