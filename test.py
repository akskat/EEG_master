import pylsl, time
print("Scanning for 3 s …")
time.sleep(3)
for info in pylsl.resolve_streams():
    print(f"name={info.name()}  type={info.type()}  ch={info.channel_count()}")
