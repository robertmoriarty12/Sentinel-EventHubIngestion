# Azure Event Hub to Microsoft Sentinel Ingestion

This repository demonstrates **two different approaches** for ingesting streaming data from Azure Event Hub into Microsoft Sentinel using the Azure Monitor Ingestion API. Both implementations accomplish the same goal but use different protocols, showcasing the architectural flexibility of Azure Event Hubs.

## Overview

Azure Event Hubs supports two protocols:
- **AMQP 1.0** (Azure's native protocol)
- **Kafka** (open-source protocol for compatibility)

This repository provides working implementations for both, allowing you to:
- Compare Event Hub SDK vs. Kafka client approaches
- Understand protocol differences in streaming data ingestion
- See why industry-standard log processors (Logstash, Graylog, OpenTelemetry) prefer Kafka endpoints
- Demonstrate streaming patterns that are incompatible with REST API-based frameworks

## What's Included

| File | Purpose |
|------|---------|
| **Event Hub SDK (AMQP)** | |
| `eventhub_to_sentinel.py` | Consumer using Azure Event Hub SDK |
| `send_sample_events.py` | Producer using Azure Event Hub SDK |
| `requirements.txt` | Dependencies for AMQP implementation |
| **Kafka Protocol** | |
| `kafka_to_sentinel.py` | Consumer using Kafka client |
| `send_sample_events_kafka.py` | Producer using Kafka client |
| `requirements_kafka.txt` | Dependencies for Kafka implementation |
| **Shared Resources** | |
| `Deploy-SentinelResources.ps1` | Deploys DCE, DCR, and custom table |
| `KAFKA_COMPARISON.md` | Detailed side-by-side comparison |

## Architecture

Both implementations follow the same data flow:

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  Data Producer  │─────▶│  Azure Event    │─────▶│  Python         │─────▶│  Microsoft      │
│  (Sample Data)  │      │  Hub            │      │  Consumer       │      │  Sentinel       │
└─────────────────┘      └─────────────────┘      └─────────────────┘      └─────────────────┘
                              ▲                         │                         ▲
                              │                         │                         │
                         Protocol:                 Transform &                    │
                       AMQP or Kafka              Filter Events             Azure Monitor
                                                                          Ingestion API (DCE/DCR)
```

**Key Components:**
- **Azure Event Hub**: Streaming platform (supports both AMQP and Kafka protocols)
- **Python Consumer**: Reads events, transforms them, sends to Sentinel
- **Data Collection Endpoint (DCE)**: Azure Monitor ingestion endpoint
- **Data Collection Rule (DCR)**: Schema mapping and routing
- **Custom Log Table**: `EventHubData_CL` in Log Analytics workspace

---

## Prerequisites

### Azure Resources
- Azure subscription
- Resource group
- Log Analytics workspace (Sentinel-enabled)
- Azure Event Hub namespace and Event Hub
- Azure AD App Registration with:
  - Client ID (Application ID)
  - Client Secret
  - Tenant ID

### Development Environment
- Python 3.8 or higher
- Azure CLI installed and authenticated
- PowerShell (for deployment script)

### Python Packages
Choose dependencies based on your implementation:
- **Event Hub SDK**: `pip install -r requirements.txt`
- **Kafka Protocol**: `pip install -r requirements_kafka.txt`

---

## Section 1: Event Hub SDK (AMQP Protocol) Implementation

This implementation uses Azure's native Event Hub SDK with the AMQP 1.0 protocol.

### Architecture Overview

The Event Hub SDK provides a native Azure experience with:
- Simple connection string authentication
- Automatic partition management
- Built-in checkpointing
- Azure-optimized performance

### Installation

```bash
# Install Event Hub SDK dependencies
pip install -r requirements.txt
```

**Dependencies:**
- `azure-eventhub==5.11.5` - Event Hub client library
- `azure-identity` - Azure authentication
- `azure-monitor-ingestion` - Send data to Sentinel

### Configuration

Edit `eventhub_to_sentinel.py` and `send_sample_events.py` with your values:

```python
# Event Hub Configuration
EVENTHUB_CONNECTION_STRING = "Endpoint=sb://NAMESPACE.servicebus.windows.net/;SharedAccessKeyName=KEY-NAME;SharedAccessKey=KEY;EntityPath=EVENTHUB-NAME"
CONSUMER_GROUP = "$Default"

# Azure AD App Registration
TENANT_ID = "your-tenant-id"
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"

# Data Collection (from deployment outputs)
DCE_ENDPOINT = "https://your-dce.ingest.monitor.azure.com"
DCR_ID = "dcr-xxxxxxxxxxxxxxxxxxxxxxxx"
STREAM_NAME = "Custom-EventHubData_CL"
```

### How It Works

**Producer (`send_sample_events.py`):**
```python
from azure.eventhub import EventHubProducerClient, EventData

producer = EventHubProducerClient.from_connection_string(
    conn_str=CONNECTION_STRING
)

# Create batch and add events
event_data_batch = producer.create_batch()
for event in events:
    event_data_batch.add(EventData(json.dumps(event)))

# Send to Event Hub
producer.send_batch(event_data_batch)
```

**Consumer (`eventhub_to_sentinel.py`):**
```python
from azure.eventhub import EventHubConsumerClient

consumer_client = EventHubConsumerClient.from_connection_string(
    conn_str=EVENTHUB_CONNECTION_STRING,
    consumer_group=CONSUMER_GROUP
)

def on_event(partition_context, event):
    # Parse event
    body_data = json.loads(event.body_as_str())
    
    # Transform to Sentinel format
    sentinel_log = {
        "TimeGenerated": event.enqueued_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EventHubSequenceNumber": event.sequence_number,
        "EventHubOffset": str(event.offset),
        "RawData": json.dumps(body_data),
        # ... merge original fields
    }
    
    # Send to Sentinel via Azure Monitor Ingestion API
    send_to_sentinel([sentinel_log])

# Consume events
consumer_client.receive(on_event=on_event, starting_position="-1")
```

### Running the Event Hub SDK Implementation

1. **Send sample events to Event Hub:**
   ```bash
   python send_sample_events.py
   ```
   Output:
   ```
   Sending events to Event Hub:
   {"id": 1, "time_generated": "2026-02-08T...", "sensor": "temperature", ...}
   ✓ Successfully sent 3 events to Event Hub
   ```

2. **Consume events and send to Sentinel:**
   ```bash
   python eventhub_to_sentinel.py
   ```
   Output:
   ```
   Step 1: Fetching events from Event Hub...
   ✓ Retrieved 3 events from Event Hub
   
   Step 2: Transforming events to Sentinel format...
   ✓ Transformed 3 events
   
   Step 3: Sending to Microsoft Sentinel...
   ✓ Successfully sent 3 events to Microsoft Sentinel
   ```

### Pros & Cons

**Advantages:**
- ✅ Simple connection string configuration
- ✅ Azure-native SDK with best practices built-in
- ✅ Automatic partition management
- ✅ Better Azure documentation support
- ✅ Lower configuration complexity

**Limitations:**
- ❌ Requires Azure-specific SDK (not portable to other platforms)
- ❌ Cannot be used by tools that only support Kafka
- ❌ Less familiar to teams with Kafka experience

---

## Section 2: Kafka Protocol Implementation

This implementation uses Kafka client libraries to connect to Event Hub's Kafka-compatible endpoint.

### Architecture Overview

Event Hub's Kafka endpoint allows:
- Zero-code migration from Apache Kafka
- Industry-standard Kafka clients
- Compatibility with Kafka ecosystem tools (Logstash, Graylog, OpenTelemetry Collector)
- Same Kafka APIs developers already know

### Installation

```bash
# Install Kafka client dependencies
pip install -r requirements_kafka.txt
```

**Dependencies:**
- `confluent-kafka==2.3.0` - Kafka client library
- `azure-identity` - Azure authentication
- `azure-monitor-ingestion` - Send data to Sentinel

### Configuration

Edit `kafka_to_sentinel.py` and `send_sample_events_kafka.py` with your values:

```python
# Event Hub (via Kafka) Configuration
EVENTHUB_NAMESPACE = "your-namespace.servicebus.windows.net"
EVENTHUB_NAME = "your-eventhub-name"
EVENTHUB_CONNECTION_STRING = "Endpoint=sb://...;SharedAccessKey=...;EntityPath=..."
CONSUMER_GROUP = "$Default"  # Kafka calls this 'group.id'

# Azure AD App Registration
TENANT_ID = "your-tenant-id"
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"

# Data Collection (from deployment outputs)
DCE_ENDPOINT = "https://your-dce.ingest.monitor.azure.com"
DCR_ID = "dcr-xxxxxxxxxxxxxxxxxxxxxxxx"
STREAM_NAME = "Custom-EventHubData_CL"
```

### How It Works

**Producer (`send_sample_events_kafka.py`):**
```python
from confluent_kafka import Producer

conf = {
    'bootstrap.servers': f'{EVENTHUB_NAMESPACE}:9093',
    'security.protocol': 'SASL_SSL',
    'sasl.mechanism': 'PLAIN',
    'sasl.username': '$ConnectionString',
    'sasl.password': EVENTHUB_CONNECTION_STRING,
}
producer = Producer(conf)

# Send events
for event in events:
    producer.produce(
        topic=EVENTHUB_NAME,
        value=json.dumps(event).encode('utf-8')
    )
producer.flush()
```

**Consumer (`kafka_to_sentinel.py`):**
```python
from confluent_kafka import Consumer

conf = {
    'bootstrap.servers': f'{EVENTHUB_NAMESPACE}:9093',
    'group.id': CONSUMER_GROUP,
    'security.protocol': 'SASL_SSL',
    'sasl.mechanism': 'PLAIN',
    'sasl.username': '$ConnectionString',
    'sasl.password': EVENTHUB_CONNECTION_STRING,
    'auto.offset.reset': 'earliest',
}
consumer = Consumer(conf)
consumer.subscribe([EVENTHUB_NAME])

while True:
    msg = consumer.poll(timeout=1.0)
    if msg is None:
        continue
    
    # Parse message
    body_data = json.loads(msg.value().decode('utf-8'))
    
    # Transform to Sentinel format
    sentinel_log = {
        "TimeGenerated": datetime.fromtimestamp(msg.timestamp()[1]/1000.0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "KafkaPartition": msg.partition(),
        "KafkaOffset": msg.offset(),
        "RawData": json.dumps(body_data),
        # ... merge original fields
    }
    
    # Send to Sentinel
    send_to_sentinel([sentinel_log])
```

### Running the Kafka Implementation

1. **Send sample events to Event Hub (via Kafka):**
   ```bash
   python send_sample_events_kafka.py
   ```
   Output:
   ```
   Sending events to Event Hub via Kafka protocol:
   ✓ Message delivered to testhub2 [partition 0] at offset 123
   ✓ Successfully sent 3 events to Event Hub via Kafka protocol
   ```

2. **Consume events and send to Sentinel:**
   ```bash
   python kafka_to_sentinel.py
   ```
   Output:
   ```
   Step 1: Connecting to Event Hub via Kafka protocol...
   ✓ Subscribed to Event Hub: testhub2
   ✓ Consumed 3 messages from Event Hub (via Kafka)
   
   Step 2: Transforming messages to Sentinel format...
   ✓ Transformed 3 messages
   
   Step 3: Sending to Microsoft Sentinel...
   ✓ Successfully sent 3 events to Microsoft Sentinel
   ```

### Pros & Cons

**Advantages:**
- ✅ Compatible with Kafka ecosystem tools (Logstash, Graylog, OpenTelemetry Collector, Splunk)
- ✅ Zero-code migration from Apache Kafka to Event Hub
- ✅ Familiar to teams with Kafka experience
- ✅ Industry-standard APIs
- ✅ Portable code (can switch between Kafka and Event Hub)

**Limitations:**
- ❌ More complex configuration (SASL authentication)
- ❌ Requires understanding of Kafka concepts
- ❌ Slightly more verbose code
- ❌ Kafka-specific error handling patterns

---

## Deployment: Setting Up Azure Resources

Both implementations require the same Azure infrastructure: DCE, DCR, and custom log table.

### Step 1: Run Deployment Script

```powershell
.\Deploy-SentinelResources.ps1 `
    -ResourceGroupName "your-resource-group" `
    -WorkspaceName "your-log-analytics-workspace" `
    -Location "centralus"
```

**Script creates:**
- Data Collection Endpoint (DCE)
- Data Collection Rule (DCR)
- Custom table: `EventHubData_CL`

**Save the outputs:**
```
DCE_ENDPOINT = "https://eventhub-dce-xxxx.region.ingest.monitor.azure.com"
DCR_ID = "dcr-xxxxxxxxxxxxxxxxxxxxxxxx"
STREAM_NAME = "Custom-EventHubData_CL"
```

### Step 2: Assign Permissions

Grant your Azure AD App Registration the "Monitoring Metrics Publisher" role:

```bash
az role assignment create \
  --assignee <YOUR-CLIENT-ID> \
  --role "Monitoring Metrics Publisher" \
  --scope "/subscriptions/<SUB-ID>/resourceGroups/<RG>/providers/Microsoft.Insights/dataCollectionRules/<DCR-NAME>"
```

### Step 3: Update Scripts

Copy the deployment outputs into your Python scripts (see Configuration sections above).

---

## Querying Data in Sentinel

After running either implementation, query your data in the Log Analytics workspace:

```kql
EventHubData_CL
| take 10
```

**Sample output:**
```
TimeGenerated             EventHubSequenceNumber  sensor        value  location
-------------------------  ----------------------  ------------ ------ -------------
2026-02-08T22:39:35Z      6                       temperature   72.5   warehouse-a
2026-02-08T22:39:35Z      7                       humidity      45.2   warehouse-b
2026-02-08T22:39:35Z      8                       pressure      101.3  warehouse-c
```

**Note:** Data may take 5-10 minutes to appear in Sentinel after ingestion.

### Query Examples

```kql
// Latest events
EventHubData_CL
| order by TimeGenerated desc
| take 100

// Filter by sensor type
EventHubData_CL
| where sensor == "temperature"
| project TimeGenerated, value, location

// Aggregate by location
EventHubData_CL
| summarize avg(value) by location, sensor
```

---

## Key Differences: Event Hub SDK vs. Kafka

| Aspect | Event Hub SDK (AMQP) | Kafka Client |
|--------|---------------------|--------------|
| **Protocol** | AMQP 1.0 | Kafka |
| **Port** | 5671 (implicit) | 9093 (explicit) |
| **Connection** | Simple connection string | Kafka broker config with SASL |
| **Library** | `azure-eventhub` | `confluent-kafka` |
| **Configuration** | Minimal | More verbose (security, SASL) |
| **Consumption Pattern** | Callback-based (`on_event`) | Polling loop (`consumer.poll()`) |
| **Error Handling** | Azure SDK exceptions | Kafka error codes |
| **Authentication** | Built into connection string | SASL with `$ConnectionString` username |
| **Event Metadata** | `event.sequence_number`, `event.offset` | `msg.offset()`, `msg.partition()` |
| **Ecosystem Compatibility** | Azure-only | Kafka ecosystem (Logstash, Graylog, etc.) |

### What's the Same?

✅ **Ingestion Logic:**
- Both consume events from Event Hub
- Both filter and transform events
- Both send to Sentinel via Azure Monitor Ingestion API

✅ **Azure Authentication:**
- Both use `ClientSecretCredential` for Sentinel ingestion
- Both require same DCE/DCR/Custom Table

✅ **Data Flow:**
- Event Hub → Consumer → Transform → Sentinel
- Same end result in the `EventHubData_CL` table

---

## Why This Matters

### For ISVs and Developers

Many organizations deploy **multi-tenant architectures** where:
- ISV owns Event Hub in their tenant
- Customer operates ingestion tool in their tenant (cross-tenant access via SAS keys)
- Customer wants to use **industry-standard processors** they already operate:
  - **Logstash** (Elastic Stack)
  - **Graylog** (centralized logging)
  - **OpenTelemetry Collector** (observability)
  - **Splunk** (SIEM/log management)

These tools have **built-in Kafka support** and can consume from Event Hub's Kafka endpoint **without any custom code**.

### For Microsoft Sentinel

**Current Gap:**
- Microsoft Sentinel's Codeless Connector Framework (CCF) only supports REST API polling
- Event Hub requires **streaming patterns** (AMQP or Kafka)
- No native Sentinel capability for cross-tenant Event Hub ingestion with SAS authentication

**Impact:**
- Customers must build custom ingestion tools (like this Python implementation)
- Cannot leverage industry-standard processors that already support Kafka
- Higher development and operational costs

### For Understanding Streaming Patterns

This repository demonstrates that **streaming protocols** (AMQP, Kafka) require fundamentally different patterns than REST APIs:
- Persistent connections (not stateless HTTP requests)
- Continuous consumption (not periodic polling)
- Partition management and offset tracking
- Checkpointing for reliable consumption

**Neither can be implemented in REST API-based frameworks without architectural changes.**

---

## Troubleshooting

### Event Hub Connection Issues

**Error: "Unable to connect to Event Hub"**
- Verify connection string is correct
- Check firewall rules on Event Hub namespace
- Ensure correct consumer group exists
- For Kafka: Verify port 9093 is accessible

### Authentication Failures

**Error: "Authentication failed" when sending to Sentinel**
- Verify Client ID, Client Secret, and Tenant ID are correct
- Confirm "Monitoring Metrics Publisher" role is assigned to the app
- Check DCR ID is the immutable ID (not the resource name)

### No Data in Sentinel

**Data not appearing in Sentinel workspace**
- Wait 5-10 minutes (ingestion delay)
- Verify DCE endpoint URL is correct
- Check DCR routing rules point to correct workspace
- Run query: `EventHubData_CL | count` to check if any data exists

### Schema Mismatches

**Error: "Schema validation failed"**
- Ensure custom table schema matches the event structure
- Verify DCR stream definition matches table columns
- Check data types (datetime, int, string) match expectations

---

## Additional Resources

### Documentation Links

**Event Hub:**
- [Azure Event Hubs Overview](https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-about)
- [Event Hubs for Apache Kafka](https://learn.microsoft.com/en-us/azure/event-hubs/azure-event-hubs-kafka-overview)
- [Event Hubs Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/eventhub-readme)

**Azure Monitor Ingestion:**
- [Logs Ingestion API Overview](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-ingestion-api-overview)
- [Data Collection Rules](https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/data-collection-rule-overview)

**Kafka Integration:**
- [Confluent Kafka Python Client](https://docs.confluent.io/kafka-clients/python/current/overview.html)
- [Logstash Kafka Input Plugin](https://www.elastic.co/guide/en/logstash/current/plugins-inputs-kafka.html)

### Repository Files

- `KAFKA_COMPARISON.md` - Detailed side-by-side code comparison
- `sentinel_setup_instructions.md` - Step-by-step Azure setup guide

---

## Contributing

Issues and pull requests are welcome! This repository is intended as a reference implementation and educational resource.

---

## License

This sample code is provided as-is under the MIT License.

---

## Summary

This repository demonstrates that **Event Hub ingestion requires streaming consumer patterns** that are fundamentally different from REST API polling. Whether using the **Event Hub SDK (AMQP)** or **Kafka client**, both approaches:

✅ Require persistent connections  
✅ Use streaming consumption patterns  
✅ Handle partitions and offsets  
✅ Cannot be implemented in REST API-based frameworks

**The Kafka implementation specifically demonstrates why ISVs prefer industry-standard tools**—Logstash, Graylog, and OpenTelemetry Collector can consume from Event Hub's Kafka endpoint without any custom code.

For organizations needing Event Hub to Sentinel ingestion today, this repository provides working reference implementations for both protocols.
