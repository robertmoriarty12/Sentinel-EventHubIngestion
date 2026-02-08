from azure.eventhub import EventHubConsumerClient
from azure.identity import ClientSecretCredential
from azure.monitor.ingestion import LogsIngestionClient
from datetime import datetime, timedelta
import json
import time
import threading

# ========== CONFIGURATION - UPDATE THESE VALUES ==========

# Event Hub Configuration
EVENTHUB_CONNECTION_STRING = "Endpoint=sb://rmoriarty.servicebus.windows.net/;SharedAccessKeyName=2;SharedAccessKey=xh6biuCUkiVpb7uqqv2jnw/WNhx1VyBc4+AEhJbXT2A=;EntityPath=testhub2"
CONSUMER_GROUP = "$Default"

# Azure AD App Registration credentials
TENANT_ID =        # From Azure AD App Registration
CLIENT_ID =         # From Azure AD App Registration
CLIENT_SECRET =  # From Azure AD App Registration

# Data Collection Endpoint and Rule (from ARM template deployment outputs)
DCE_ENDPOINT = "https://eventhub-dce-7856-5wdo.centralus-1.ingest.monitor.azure.com"     # e.g., https://testdata-dce-xxx.region.ingest.monitor.azure.com
DCR_ID = "dcr-bcbd6428c1b24271a4dd423e90e654f8"           # e.g., dcr-xxxxxxxxxxxxxxxxxxxxxxxxxx
STREAM_NAME = "Custom-EventHubData_CL"  # Custom table name

# Time filter settings
FILTER_HOURS_AGO = 24  # Only process events from last 24 hours (set to None for all)
MAX_WAIT_TIME = 10     # Seconds to wait for events before stopping

# ========================================================

def filter_event_by_time_generated(event, hours_ago=None):
    """Filter events based on time_generated field in the JSON payload"""
    if hours_ago is None:
        return True
    
    try:
        # Parse the event body to get time_generated
        body_data = json.loads(event.body_as_str())
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

def filter_event_by_time(event, hours_ago=None):
    """Filter events based on enqueued time (deprecated - kept for compatibility)"""
    if hours_ago is None:
        return True
    
    cutoff_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else None).replace(tzinfo=None) - timedelta(hours=hours_ago)
    return event.enqueued_time.replace(tzinfo=None) >= cutoff_time

def transform_event_to_sentinel_format(event):
    """Transform Event Hub event to Sentinel-compatible format"""
    try:
        # Try to parse as JSON
        body_data = json.loads(event.body_as_str())
    except json.JSONDecodeError:
        # If not JSON, wrap the body as a message
        body_data = {"Message": event.body_as_str()}
    
    # Create Sentinel log entry
    sentinel_log = {
        "TimeGenerated": event.enqueued_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EventHubSequenceNumber": event.sequence_number,
        "EventHubOffset": str(event.offset),
        "EventHubEnqueuedTime": event.enqueued_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    print(f"  DCR ID: {DCR_ID}")
    print(f"  Stream Name: {STREAM_NAME}")
    print(f"  Records to send: {len(logs)}\n")
    
    try:
        # Authenticate with Azure
        print("Authenticating with Azure...")
        credential = ClientSecretCredential(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        print("✓ Authentication successful\n")
        
        # Create ingestion client
        print("Creating ingestion client...")
        client = LogsIngestionClient(
            endpoint=DCE_ENDPOINT,
            credential=credential,
            logging_enable=True
        )
        print("✓ Client created successfully\n")
        
        # Send logs
        print(f"Sending {len(logs)} records to Microsoft Sentinel...")
        client.upload(
            rule_id=DCR_ID,
            stream_name=STREAM_NAME,
            logs=logs
        )
        
        print(f"\n{'='*70}")
        print("✓ SUCCESS! Data has been ingested.")
        print(f"  Records sent: {len(logs)}")
        print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"\nTo query your data in Sentinel, use this KQL query:")
        print(f"  {STREAM_NAME.replace('Custom-', '')} | take 10")
        print(f"\nNote: It may take 5-10 minutes for data to appear in Sentinel")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: Failed to send data to Sentinel")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def consume_eventhub_and_send_to_sentinel():
    """Consume events from Event Hub and send to Sentinel"""
    consumer_client = EventHubConsumerClient.from_connection_string(
        conn_str=EVENTHUB_CONNECTION_STRING,
        consumer_group=CONSUMER_GROUP
    )
    
    all_events = []
    stop_event = threading.Event()
    last_event_time = [time.time()]
    
    def on_event(partition_context, event):
        """Callback to collect events"""
        last_event_time[0] = time.time()
        if filter_event_by_time_generated(event, FILTER_HOURS_AGO):
            all_events.append(event)
    
    def monitor_and_stop():
        """Monitor for inactivity and stop consuming"""
        while not stop_event.is_set():
            time.sleep(1)
            if time.time() - last_event_time[0] > MAX_WAIT_TIME:
                print(f"\nNo events received for {MAX_WAIT_TIME} seconds, stopping Event Hub consumption...")
                consumer_client.close()
                break
    
    try:
        print(f"{'='*70}")
        print("Event Hub to Microsoft Sentinel Data Pipeline")
        print(f"{'='*70}\n")
        print("Step 1: Fetching events from Event Hub...")
        
        # Get partition IDs
        partition_ids = consumer_client.get_partition_ids()
        print(f"Found {len(partition_ids)} partition(s)\n")
        
        # Start monitor thread
        monitor_thread = threading.Thread(target=monitor_and_stop, daemon=True)
        monitor_thread.start()
        
        print("Reading from all partitions...")
        
        # Receive from all partitions
        consumer_client.receive(
            on_event=on_event,
            starting_position="-1",  # Start from beginning
        )
        
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        # Expected when we close the client from monitor thread
        if "close" not in str(e).lower():
            print(f"Error: {e}")
    finally:
        stop_event.set()
        try:
            consumer_client.close()
        except:
            pass
    
    print(f"\n{'='*70}")
    print(f"Step 1 Complete: Retrieved {len(all_events)} events from Event Hub")
    print(f"{'='*70}\n")
    
    if all_events:
        # Transform events to Sentinel format
        print("Step 2: Transforming events to Sentinel format...")
        sentinel_logs = [transform_event_to_sentinel_format(event) for event in all_events]
        print(f"✓ Transformed {len(sentinel_logs)} events\n")
        
        # Display sample
        print("Sample transformed data (first record):")
        print(json.dumps(sentinel_logs[0], indent=2))
        print()
        
        # Send to Sentinel
        print("Step 3: Sending to Microsoft Sentinel...")
        send_to_sentinel(sentinel_logs)
    else:
        print("No events to process. Event Hub is empty or all events are filtered out.")
    
    return all_events

if __name__ == "__main__":
    print("\n" + "="*70)
    print("Event Hub to Sentinel Ingestion Script")
    print("="*70 + "\n")
    
    # Validate configuration
    if "<your-" in TENANT_ID or "<your-" in CLIENT_ID or "<dce-" in DCE_ENDPOINT:
        print("❌ ERROR: Please configure the script with your Azure credentials!")
        print("\nYou need to update the following variables:")
        print("  - TENANT_ID")
        print("  - CLIENT_ID")
        print("  - CLIENT_SECRET")
        print("  - DCE_ENDPOINT")
        print("  - DCR_ID")
        print("\nSee the README for detailed setup instructions.")
    else:
        consume_eventhub_and_send_to_sentinel()

