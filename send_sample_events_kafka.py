from confluent_kafka import Producer
from datetime import datetime, timedelta
import json

# Event Hub Configuration (via Kafka)
EVENTHUB_NAMESPACE = "rmoriarty.servicebus.windows.net"
EVENTHUB_NAME = "testhub2"
EVENTHUB_CONNECTION_STRING = ""

def delivery_report(err, msg):
    """Callback for message delivery reports"""
    if err is not None:
        print(f'❌ Message delivery failed: {err}')
    else:
        print(f'✓ Message delivered to {msg.topic()} [partition {msg.partition()}] at offset {msg.offset()}')

def send_sample_events_kafka():
    """
    Send sample JSON events with different timestamps using Kafka protocol
    """
    
    # Kafka producer configuration for Event Hub
    conf = {
        'bootstrap.servers': f'{EVENTHUB_NAMESPACE}:9093',
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': '$ConnectionString',
        'sasl.password': EVENTHUB_CONNECTION_STRING,
        'client.id': 'python-kafka-producer'
    }
    
    producer = Producer(conf)
    
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
        print("Sending events to Event Hub via Kafka protocol:\n")
        
        for event in events:
            event_json = json.dumps(event)
            print(f"Sending: {event_json}")
            
            # Send to Event Hub (which is the Kafka topic name)
            producer.produce(
                topic=EVENTHUB_NAME,
                value=event_json.encode('utf-8'),
                callback=delivery_report
            )
        
        # Wait for message deliveries
        print("\nWaiting for message delivery confirmations...")
        producer.flush()
        
        print("\n✓ Successfully sent 3 events to Event Hub via Kafka protocol")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n" + "="*70)
    print("Send Sample Events to Event Hub (via Kafka Protocol)")
    print("="*70 + "\n")
    
    # Validate configuration
    if "your-namespace" in EVENTHUB_NAMESPACE:
        print("❌ ERROR: Please configure the script with your Event Hub details!")
        print("\nYou need to update the following variables:")
        print("  - EVENTHUB_NAMESPACE")
        print("  - EVENTHUB_NAME")
        print("  - EVENTHUB_CONNECTION_STRING")
    else:
        send_sample_events_kafka()

