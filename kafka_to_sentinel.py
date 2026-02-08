from confluent_kafka import Consumer, KafkaError, KafkaException
from azure.identity import ClientSecretCredential
from azure.monitor.ingestion import LogsIngestionClient
from datetime import datetime, timedelta
import json
import time
import sys

# ========== CONFIGURATION - UPDATE THESE VALUES ==========

# Event Hub (via Kafka) Configuration
EVENTHUB_NAMESPACE = "rmoriarty.servicebus.windows.net"
EVENTHUB_NAME = "testhub2"
EVENTHUB_CONNECTION_STRING = "Endpoint=sb://rmoriarty.servicebus.windows.net/;SharedAccessKeyName=2;SharedAccessKey=xh6biuCUkiVpb7uqqv2jnw/WNhx1VyBc4+AEhJbXT2A=;EntityPath=testhub2"
CONSUMER_GROUP = "$Default"  # Kafka calls this 'group.id'

# Azure AD App Registration credentials
TENANT_ID = "d101101f-3558-4acd-8438-21759bb989e4"          # From Azure AD App Registration
CLIENT_ID = "e70a5644-8117-44ce-a77d-dbccbf997ca8"          # From Azure AD App Registration
CLIENT_SECRET = "xtA8Q~xyDyc4UgwIO3K04zL2GXPItaZIreQyyaCR"  # From Azure AD App Registration

# Data Collection Endpoint and Rule (from ARM template deployment outputs)
DCE_ENDPOINT = "https://eventhub-dce-7856-5wdo.centralus-1.ingest.monitor.azure.com"     # e.g., https://testdata-dce-xxx.region.ingest.monitor.azure.com
DCR_ID = "dcr-bcbd6428c1b24271a4dd423e90e654f8"           # e.g., dcr-xxxxxxxxxxxxxxxxxxxxxxxxxx
STREAM_NAME = "Custom-EventHubData_CL"  # Custom table name

# Time filter settings
FILTER_HOURS_AGO = 24  # Only process events from last 24 hours (set to None for all)
MAX_WAIT_TIME = 10     # Seconds to wait for events before stopping

# ========================================================

def filter_event_by_time_generated(message_value, hours_ago=None):
    """Filter events based on time_generated field in the JSON payload"""
    if hours_ago is None:
        return True
    
    try:
        # Parse the message value to get time_generated
        body_data = json.loads(message_value)
        time_generated_str = body_data.get('time_generated')
        
        if not time_generated_str:
            # If no time_generated field, include the event
            return True
        
        # Parse the ISO timestamp
        time_generated = datetime.fromisoformat(time_generated_str.replace('Z', '+00:00'))
        cutoff_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None) - timedelta(hours=hours_ago)
        
        return time_generated.replace(tzinfo=None) >= cutoff_time.replace(tzinfo=None)
    except (json.JSONDecodeError, ValueError, AttributeError):
        # If parsing fails, include the event
        return True

def transform_kafka_message_to_sentinel_format(msg):
    """Transform Kafka message to Sentinel-compatible format"""
    try:
        # Try to parse as JSON
        body_data = json.loads(msg.value().decode('utf-8'))
    except json.JSONDecodeError:
        # If not JSON, wrap the body as a message
        body_data = {"Message": msg.value().decode('utf-8')}
    
    # Create Sentinel log entry
    # Note: Kafka doesn't have EventHubSequenceNumber/Offset in same format
    # We use Kafka's partition/offset metadata
    sentinel_log = {
        "TimeGenerated": datetime.fromtimestamp(msg.timestamp()[1] / 1000.0).strftime("%Y-%m-%dT%H:%M:%SZ") if msg.timestamp()[1] else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "KafkaPartition": msg.partition(),
        "KafkaOffset": msg.offset(),
        "KafkaTopic": msg.topic(),
        "KafkaTimestamp": datetime.fromtimestamp(msg.timestamp()[1] / 1000.0).strftime("%Y-%m-%dT%H:%M:%SZ") if msg.timestamp()[1] else None,
        "RawData": json.dumps(body_data),
    }
    
    # Merge original data fields if it's JSON
    if isinstance(body_data, dict):
        # Flatten nested JSON for Sentinel (optional)
        for key, value in body_data.items():
            if isinstance(value, (str, int, float, bool)):
                sentinel_log[key] = value
            else:
                sentinel_log[key] = json.dumps(value)
    
    return sentinel_log

def send_to_sentinel(logs):
    """Send logs to Microsoft Sentinel via Azure Monitor Ingestion API"""
    if not logs:
        print("No logs to send.")
        return
    
    print(f"\n{'='*70}")
    print("Sending data to Microsoft Sentinel...")
    print(f"{'='*70}\n")
    
    print(f"Configuration:")
    print(f"  Tenant ID: {TENANT_ID[:20]}...")
    print(f"  Client ID: {CLIENT_ID[:20]}...")
    print(f"  DCE Endpoint: {DCE_ENDPOINT}")
    print(f"  DCR ID: {DCR_ID[:20]}...")
    print(f"  Stream Name: {STREAM_NAME}")
    print(f"  Number of logs: {len(logs)}\n")
    
    try:
        # Create credential and client
        credential = ClientSecretCredential(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        
        client = LogsIngestionClient(endpoint=DCE_ENDPOINT, credential=credential)
        
        # Send logs
        client.upload(rule_id=DCR_ID, stream_name=STREAM_NAME, logs=logs)
        
        print(f"✓ Successfully sent {len(logs)} events to Microsoft Sentinel")
        print(f"\nData ingestion completed at {datetime.utcnow().isoformat()}Z UTC")
        print(f"\nTo query your data in Sentinel, use this KQL query:")
        print(f"  {STREAM_NAME.replace('Custom-', '')} | take 10")
        print(f"\nNote: It may take 5-10 minutes for data to appear in Sentinel")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: Failed to send data to Sentinel")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def consume_kafka_and_send_to_sentinel():
    """Consume events from Event Hub (via Kafka protocol) and send to Sentinel"""
    
    # Kafka consumer configuration for Event Hub
    conf = {
        'bootstrap.servers': f'{EVENTHUB_NAMESPACE}:9093',
        'group.id': CONSUMER_GROUP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': '$ConnectionString',
        'sasl.password': EVENTHUB_CONNECTION_STRING,
        'auto.offset.reset': 'earliest',  # Start from beginning (like starting_position="-1")
        'enable.auto.commit': True,
        'session.timeout.ms': 6000,
        'api.version.request': True
    }
    
    consumer = Consumer(conf)
    
    all_messages = []
    last_message_time = time.time()
    
    try:
        print(f"{'='*70}")
        print("Event Hub to Microsoft Sentinel Data Pipeline (via Kafka Protocol)")
        print(f"{'='*70}\n")
        print("Step 1: Connecting to Event Hub via Kafka protocol...")
        
        # Subscribe to the Event Hub (topic in Kafka terminology)
        consumer.subscribe([EVENTHUB_NAME])
        
        print(f"✓ Subscribed to Event Hub: {EVENTHUB_NAME}")
        print(f"✓ Consumer Group: {CONSUMER_GROUP}\n")
        print("Reading messages (press Ctrl+C to stop)...\n")
        
        while True:
            msg = consumer.poll(timeout=1.0)
            
            if msg is None:
                # Check for timeout
                if time.time() - last_message_time > MAX_WAIT_TIME:
                    print(f"\n⏱ No new messages for {MAX_WAIT_TIME} seconds, stopping...")
                    break
                continue
            
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # End of partition, not an error
                    continue
                else:
                    raise KafkaException(msg.error())
            
            # Update last message time
            last_message_time = time.time()
            
            # Filter by time if configured
            if filter_event_by_time_generated(msg.value().decode('utf-8'), FILTER_HOURS_AGO):
                all_messages.append(msg)
                print(f"  [Partition {msg.partition()}] Offset {msg.offset()}: Received event")
        
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        consumer.close()
    
    print(f"\n{'='*70}")
    print(f"✓ Consumed {len(all_messages)} messages from Event Hub (via Kafka)")
    print(f"{'='*70}\n")
    
    if all_messages:
        # Transform messages
        print("Step 2: Transforming messages to Sentinel format...")
        sentinel_logs = [transform_kafka_message_to_sentinel_format(msg) for msg in all_messages]
        print(f"✓ Transformed {len(sentinel_logs)} messages\n")
        
        # Display sample
        print("Sample transformed data (first record):")
        print(json.dumps(sentinel_logs[0], indent=2))
        print()
        
        # Send to Sentinel
        print("Step 3: Sending to Microsoft Sentinel...")
        send_to_sentinel(sentinel_logs)
    else:
        print("No messages to process. Event Hub is empty or all messages are filtered out.")
    
    return all_messages

if __name__ == "__main__":
    print("\n" + "="*70)
    print("Event Hub to Sentinel Ingestion Script (Kafka Protocol)")
    print("="*70 + "\n")
    
    # Validate configuration
    if "<your-" in TENANT_ID or "<your-" in CLIENT_ID or "<dce-" in DCE_ENDPOINT:
        print("❌ ERROR: Please configure the script with your Azure credentials!")
        print("\nYou need to update the following variables:")
        print("  - EVENTHUB_NAMESPACE")
        print("  - EVENTHUB_NAME")
        print("  - EVENTHUB_CONNECTION_STRING")
        print("  - TENANT_ID")
        print("  - CLIENT_ID")
        print("  - CLIENT_SECRET")
        print("  - DCE_ENDPOINT")
        print("  - DCR_ID")
        print("\nSee the README for detailed setup instructions.")
    else:
        consume_kafka_and_send_to_sentinel()
