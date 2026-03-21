# Lab 3

## Setup
1. `cd lab3/`
2. Install the [uv python package manager](https://docs.astral.sh/uv/getting-started/installation) for your system.
3. `uv sync`

## Protocol State Machines

### Client Architecture
```mermaid
stateDiagram-v2
    %% Client
    direction TB

    [*] --> INIT
    INIT --> SEND_REQUEST : File opened successfully
    SEND_REQUEST --> WAIT_FOR_DATA : Send REQUEST packet
    WAIT_FOR_DATA --> DONE : Rx Final DATA (payload < max_size)<br>Write chunk, Send final ACK
    DONE --> [*] : Transfer Complete
    
    INIT --> ERROR : File IO Error
    WAIT_FOR_DATA --> ERROR : Rx ERROR packet
    ERROR --> [*] : Transfer Aborted
    
    WAIT_FOR_DATA --> SEND_REQUEST : Timeout (expected_seq == 0)<br>Resend REQUEST
    WAIT_FOR_DATA --> WAIT_FOR_DATA : Rx Expected DATA<br>Write chunk, Send ACK, seq++
    WAIT_FOR_DATA --> WAIT_FOR_DATA : Timeout (expected_seq > 0)<br>Resend previous ACK
    WAIT_FOR_DATA --> WAIT_FOR_DATA : Rx Duplicate DATA (seq < expected)<br>Resend ACK
```

### Server Architecture
```mermaid
stateDiagram-v2
    %% Server States
    [*] --> LISTEN
    
    LISTEN --> LISTEN : Rx REQUEST (File not found)<br>Send ERROR
    LISTEN --> SEND_DATA : Rx REQUEST (File exists)<br>Parse seg_size, Open file, Read chunk
    
    SEND_DATA --> WAIT_ACK : Send DATA packet
    
    WAIT_ACK --> WAIT_ACK : Timeout<br>Resend DATA
    WAIT_ACK --> WAIT_ACK : Rx Duplicate REQUEST<br>Resend DATA
    WAIT_ACK --> SEND_DATA : Rx ACK (seq == expected)<br>seq++, Read next chunk
    
    WAIT_ACK --> TIME_WAIT : Rx Final ACK<br>Close file, Start 5s timer
    
    TIME_WAIT --> TIME_WAIT : Rx Stray ACK / REQUEST<br>Resend final DATA
    TIME_WAIT --> LISTEN : 5 seconds elapsed<br>Discard connection state
    TIME_WAIT --> LISTEN : Rx NEW Client REQUEST<br>Reset to handle new transfer
```

## Testing Application Layer Defined Reliable Data Transfer (RDT) over UDP
### Part 1

1. Start the server process:
```sh
uv run server.py 8080
```

2. Start the client in a separate terminal to begin the file transfer:
```sh
uv run client.py 127.0.0.1 8080 test.txt --segment-size 512
```
> Note: The file you specify must exist in the `data/` directory.

### Part 2