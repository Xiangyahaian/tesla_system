#!/usr/bin/env python3
import pickle
import os

for filename in os.listdir('.'):
    if filename.endswith('.pkl'):
        print(f"\n{'='*50}")
        print(f"文件: {filename}")
        print('='*50)
        
        with open(filename, 'rb') as f:
            data = pickle.load(f)
        
        if isinstance(data, list):
            for i, item in enumerate(data[:5]):
                print(f"\n[{i}] {item}")
        elif isinstance(data, dict):
            for i, (k, v) in enumerate(list(data.items())[:5]):
                print(f"\n[{i}] {k}: {v}")
        else:
            print(data)
