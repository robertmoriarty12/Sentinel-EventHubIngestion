from azure.eventhub import EventHubProducerClient, EventData
from datetime import datetime, timedelta
import json

# Your Event Hub connection string
CONNECTION_STRING = "Endpoint=sb://rmoriarty.servicebus.windows.net/;SharedAccessKeyName=2;SharedAccessKey=xh6biuCUkiVpb7uqqv2jnw/WNhx1VyBc4+AEhJbXT2A=;EntityPath=testhub2"

def send_sample_events():
    """
    Send sample JSON events with different timestamps
    """
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING
    )
    
    # Create timestamps
    now = datetime.utcnow()
    one_hour_ago = now - timedelta(hours=1)
    
    # Sample events
    events = [
        {
            "id": 1,
            "time_generated": now.isoformat() + "Z",
            "sensor": "temperature",
            "value": 72.5,
            "location": "warehouse-a"
        },
        {
            "id": 2,
            "time_generated": one_hour_ago.isoformat() + "Z",
            "sensor": "humidity",
            "value": 45.2,
            "location": "warehouse-b"
        },
        {
            "id": 3,
            "time_generated": one_hour_ago.isoformat() + "Z",
            "sensor": "pressure",
            "value": 101.3,
            "location": "warehouse-c"
        }
    ]
    
    try:
        # Create a batch
        event_data_batch = producer.create_batch()
        
        print("Sending events to Event Hub:\n")
        for event in events:
            event_json = json.dumps(event)
            print(event_json)
            event_data_batch.add(EventData(event_json))
        
        # Send the batch
        producer.send_batch(event_data_batch)
        print("\n✓ Successfully sent 3 events to Event Hub")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        producer.close()

if __name__ == "__main__":
    send_sample_events()
