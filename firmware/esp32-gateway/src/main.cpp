/**
 * ESP32 Standalone Meshtastic -> MQTT -> Shelly Secure Gateway
 *
 * Architecture:
 *
 *   ESP32 SoftAP
 *       |
 *       +-- Meshtastic MQTT gateway
 *       +-- Shelly relay
 *       +-- optional PC for diagnostics
 *
 *   ESP32 IP:
 *       192.168.4.1
 *
 *   MQTT broker:
 *       sMQTTBroker
 *       TCP port 1883
 *
 * Security:
 *   1. Meshtastic sender whitelist
 *   2. Shelly target whitelist
 *   3. Action whitelist
 *   4. Per-sender monotonic sequence / replay protection
 *   5. HMAC-SHA256 authentication
 *
 * Expected Meshtastic JSON:
 *
 * {
 *   "channel":0,
 *   "from":3439707795,
 *   "payload":{
 *      "action":"ON",
 *      "seq":517203,
 *      "sig":"b2dddd6c",
 *      "target":"shelly1-01",
 *      "ver":1
 *   },
 *   "sender":"!433ab01c",
 *   "type":"text"
 * }
 */

#include <Arduino.h>
#include <WiFi.h>
#include <sMQTTBroker.h>
#include <ArduinoJson.h>
#include "mbedtls/md.h"


// ============================================================
// CONFIGURATION
// Loaded from .env via load_env.py
// ============================================================

#ifndef WIFI_SSID_RX
#define WIFI_SSID_RX "ESP32_MQTT_AP"
#endif

#ifndef WIFI_PASS_RX
#define WIFI_PASS_RX "ChangeThisPassword"
#endif

#ifndef CONTROL_SECRET
#define CONTROL_SECRET "MeshShellySecret2026"
#endif

#ifndef MESH_LORA_REGION
#define MESH_LORA_REGION "EU_868"
#endif

#ifndef MESH_GATEWAY_NODE_ID
#define MESH_GATEWAY_NODE_ID 0x00000000
#endif


static const char* WIFI_SSID =
    WIFI_SSID_RX;

static const char* WIFI_PASS =
    WIFI_PASS_RX;

static const char* CONTROL_SECRET_STR =
    CONTROL_SECRET;

static const char* MESH_LORA_REGION_STR =
    MESH_LORA_REGION;

static const uint32_t MESH_GATEWAY_NODE_ID_VAL =
    MESH_GATEWAY_NODE_ID;


// ============================================================
// NETWORK
// ============================================================

static const uint16_t MQTT_PORT = 1883;

static const IPAddress AP_IP(
    192, 168, 4, 1
);

static const IPAddress AP_GATEWAY(
    192, 168, 4, 1
);

static const IPAddress AP_SUBNET(
    255, 255, 255, 0
);


// ============================================================
// SECURITY CONFIGURATION
// ============================================================

static const int COMMAND_VERSION = 1;


// ------------------------------------------------------------
// Meshtastic nodes authorized to control devices
//
// Add additional nodes if needed:
//
// "!433ab01c",
// "!12345678"
//
// "*" can be used during development to allow all senders,
// but should NOT be used in production.
// ------------------------------------------------------------

static const char* ALLOWED_NODES[] =
{
    "!433ab01c"
};

static const size_t ALLOWED_NODES_COUNT =
    sizeof(ALLOWED_NODES) /
    sizeof(ALLOWED_NODES[0]);


// ------------------------------------------------------------
// Allowed Shelly devices
// ------------------------------------------------------------

static const char* ALLOWED_TARGETS[] =
{
    "shelly1-01"
};

static const size_t ALLOWED_TARGETS_COUNT =
    sizeof(ALLOWED_TARGETS) /
    sizeof(ALLOWED_TARGETS[0]);


static const size_t MAX_TRACKED_NODES = 16;


// ============================================================
// HMAC-SHA256
// ============================================================

static void hmacSha256(
    const char* key,
    const char* message,
    uint8_t output[32]
)
{
    const mbedtls_md_info_t* mdInfo =
        mbedtls_md_info_from_type(
            MBEDTLS_MD_SHA256
        );

    if (mdInfo == nullptr)
    {
        memset(
            output,
            0,
            32
        );

        return;
    }


    mbedtls_md_context_t ctx;

    mbedtls_md_init(
        &ctx
    );


    int rc =
        mbedtls_md_setup(
            &ctx,
            mdInfo,
            1
        );


    if (rc != 0)
    {
        memset(
            output,
            0,
            32
        );

        mbedtls_md_free(
            &ctx
        );

        return;
    }


    mbedtls_md_hmac_starts(
        &ctx,
        reinterpret_cast<const unsigned char*>(
            key
        ),
        strlen(key)
    );


    mbedtls_md_hmac_update(
        &ctx,
        reinterpret_cast<const unsigned char*>(
            message
        ),
        strlen(message)
    );


    mbedtls_md_hmac_finish(
        &ctx,
        output
    );


    mbedtls_md_free(
        &ctx
    );
}


// ============================================================
// First 4 bytes of SHA256 digest -> 8 hexadecimal characters
// ============================================================

static String hexEncodeTruncated8(
    const uint8_t digest[32]
)
{
    char hex[9];


    for (int i = 0; i < 4; i++)
    {
        snprintf(
            hex + (i * 2),
            3,
            "%02x",
            digest[i]
        );
    }


    hex[8] = '\0';


    return String(
        hex
    );
}


// ============================================================
// Signature:
// HMAC-SHA256(secret, "target:ACTION:seq")
// ============================================================

static String computeHmacSig(
    const String& target,
    const String& action,
    uint32_t seq
)
{
    String actionUpper =
        action;

    actionUpper.toUpperCase();


    String canonical =
        target +
        ":" +
        actionUpper +
        ":" +
        String(seq);


    uint8_t digest[32];


    hmacSha256(
        CONTROL_SECRET_STR,
        canonical.c_str(),
        digest
    );


    return hexEncodeTruncated8(
        digest
    );
}


// ============================================================
// Constant-time signature comparison
// ============================================================

static bool constantTimeEquals(
    const String& a,
    const String& b
)
{
    if (
        a.length() !=
        b.length()
    )
    {
        return false;
    }


    uint8_t diff = 0;


    for (
        size_t i = 0;
        i < a.length();
        i++
    )
    {
        diff |=
            static_cast<uint8_t>(
                a[i]
            )
            ^
            static_cast<uint8_t>(
                b[i]
            );
    }


    return diff == 0;
}


// ============================================================
// SENDER WHITELIST
// ============================================================

static bool isSenderAllowed(
    const String& sender
)
{
    for (
        size_t i = 0;
        i < ALLOWED_NODES_COUNT;
        i++
    )
    {
        if (
            strcmp(
                ALLOWED_NODES[i],
                "*"
            )
            == 0
        )
        {
            return true;
        }


        if (
            sender.equals(
                ALLOWED_NODES[i]
            )
        )
        {
            return true;
        }
    }


    return false;
}


// ============================================================
// TARGET WHITELIST
// ============================================================

static bool isTargetAllowed(
    const String& target
)
{
    for (
        size_t i = 0;
        i < ALLOWED_TARGETS_COUNT;
        i++
    )
    {
        if (
            target.equals(
                ALLOWED_TARGETS[i]
            )
        )
        {
            return true;
        }
    }


    return false;
}


// ============================================================
// ANTI-REPLAY
// ============================================================

struct NodeSeqEntry
{
    String nodeId;

    uint32_t lastSeenSeq = 0;

    bool used = false;
};


static NodeSeqEntry nodeSeqTable[
    MAX_TRACKED_NODES
];


// ============================================================

static bool getLastSeenSeq(
    const String& nodeId,
    uint32_t& value
)
{
    for (
        size_t i = 0;
        i < MAX_TRACKED_NODES;
        i++
    )
    {
        if (
            nodeSeqTable[i].used
            &&
            nodeSeqTable[i].nodeId.equals(
                nodeId
            )
        )
        {
            value =
                nodeSeqTable[i].lastSeenSeq;

            return true;
        }
    }


    value = 0;

    return false;
}


// ============================================================

static void setLastSeenSeq(
    const String& nodeId,
    uint32_t seq
)
{
    // Update existing node

    for (
        size_t i = 0;
        i < MAX_TRACKED_NODES;
        i++
    )
    {
        if (
            nodeSeqTable[i].used
            &&
            nodeSeqTable[i].nodeId.equals(
                nodeId
            )
        )
        {
            nodeSeqTable[i].lastSeenSeq =
                seq;

            return;
        }
    }


    // Insert new node

    for (
        size_t i = 0;
        i < MAX_TRACKED_NODES;
        i++
    )
    {
        if (
            !nodeSeqTable[i].used
        )
        {
            nodeSeqTable[i].used =
                true;

            nodeSeqTable[i].nodeId =
                nodeId;

            nodeSeqTable[i].lastSeenSeq =
                seq;

            return;
        }
    }


    // Table full.
    // With a small whitelist this should practically never occur.

    nodeSeqTable[0].used =
        true;

    nodeSeqTable[0].nodeId =
        nodeId;

    nodeSeqTable[0].lastSeenSeq =
        seq;
}


// ============================================================
// SECURITY LOGGING
// ============================================================

static void securityReject(
    const char* reason
)
{
    Serial.printf(
        "[SECURITY] REJECTED: %s\n",
        reason
    );

    Serial.println(
        "----------------------------------------"
    );
}


// ============================================================
// MQTT BROKER
// ============================================================

class MeshtasticBroker :
    public sMQTTBroker
{
public:

    bool onEvent(
        sMQTTEvent* event
    ) override
    {
        switch (
            event->Type()
        )
        {

            // =================================================
            // CLIENT CONNECTED
            // =================================================

            case NewClient_sMQTTEventType:
            {
                Serial.println(
                    "[MQTT] Client connected"
                );

                break;
            }


            // =================================================
            // CLIENT DISCONNECTED
            // =================================================

            case RemoveClient_sMQTTEventType:
            {
                Serial.println(
                    "[MQTT] Client disconnected"
                );

                break;
            }


            // =================================================
            // MQTT PUBLICATION
            // =================================================

            case Public_sMQTTEventType:
            {
                sMQTTPublicClientEvent* pub =
                    static_cast<
                        sMQTTPublicClientEvent*
                    >(
                        event
                    );


                std::string topicStd =
                    pub->Topic();

                std::string payloadStd =
                    pub->Payload();


                String topic(
                    topicStd.c_str()
                );


                // =================================================
                // ONLY parse Meshtastic JSON.
                //
                // Ignore binary / protobuf MQTT traffic such as
                // msh/2/e/...
                // =================================================

                if (
                    !topic.startsWith(
                        "msh/2/json/"
                    )
                )
                {
                    return true;
                }


                Serial.println();

                Serial.println(
                    "========================================"
                );

                Serial.println(
                    "[MESHTASTIC] JSON command received"
                );


                Serial.printf(
                    "[MESHTASTIC] Topic: %s\n",
                    topic.c_str()
                );


                Serial.printf(
                    "[MESHTASTIC] Payload: %s\n",
                    payloadStd.c_str()
                );


                // =================================================
                // PARSE JSON ENVELOPE
                // =================================================

                JsonDocument doc;


                DeserializationError err =
                    deserializeJson(
                        doc,
                        payloadStd.c_str()
                    );


                if (err)
                {
                    Serial.printf(
                        "[JSON] Error: %s\n",
                        err.c_str()
                    );


                    securityReject(
                        "Invalid JSON"
                    );


                    return true;
                }


                // =================================================
                // TYPE CHECK
                // =================================================

                const char* type =
                    doc["type"] | "";


                if (
                    strcmp(
                        type,
                        "text"
                    )
                    != 0
                )
                {
                    securityReject(
                        "Meshtastic type is not text"
                    );


                    return true;
                }


                // =================================================
                // EXTRACT COMMAND
                // =================================================

                String sender =
                    doc["sender"] | "";


                JsonVariant payload =
                    doc["payload"];


                if (
                    !payload.is<JsonObject>()
                )
                {
                    securityReject(
                        "payload is not a JSON object"
                    );


                    return true;
                }


                String target =
                    payload["target"] | "";

                String action =
                    payload["action"] | "";

                String sig =
                    payload["sig"] | "";

                uint32_t seq =
                    payload["seq"] | 0;

                int version =
                    payload["ver"] | 0;


                action.toUpperCase();

                sig.toLowerCase();


                Serial.println();

                Serial.printf(
                    "[COMMAND] Sender : %s\n",
                    sender.c_str()
                );

                Serial.printf(
                    "[COMMAND] Target : %s\n",
                    target.c_str()
                );

                Serial.printf(
                    "[COMMAND] Action : %s\n",
                    action.c_str()
                );

                Serial.printf(
                    "[COMMAND] Seq    : %lu\n",
                    static_cast<unsigned long>(
                        seq
                    )
                );

                Serial.printf(
                    "[COMMAND] Sig    : %s\n",
                    sig.c_str()
                );

                Serial.printf(
                    "[COMMAND] Ver    : %d\n",
                    version
                );


                // =================================================
                // REQUIRED FIELDS
                // =================================================

                if (
                    sender.isEmpty()
                    ||
                    target.isEmpty()
                    ||
                    action.isEmpty()
                    ||
                    sig.isEmpty()
                    ||
                    seq == 0
                )
                {
                    securityReject(
                        "Missing required command field"
                    );


                    return true;
                }


                // =================================================
                // PROTOCOL VERSION
                // =================================================

                if (
                    version !=
                    COMMAND_VERSION
                )
                {
                    securityReject(
                        "Unsupported command version"
                    );


                    return true;
                }


                // =================================================
                // CHECK 1/4:
                // SENDER WHITELIST
                // =================================================

                if (
                    !isSenderAllowed(
                        sender
                    )
                )
                {
                    Serial.printf(
                        "[SECURITY] Unauthorized sender: %s\n",
                        sender.c_str()
                    );


                    securityReject(
                        "Sender whitelist"
                    );


                    return true;
                }


                Serial.println(
                    "[Security 1/4] Sender whitelist OK"
                );


                // =================================================
                // CHECK 2/4:
                // TARGET WHITELIST
                // =================================================

                if (
                    !isTargetAllowed(
                        target
                    )
                )
                {
                    Serial.printf(
                        "[SECURITY] Unauthorized target: %s\n",
                        target.c_str()
                    );


                    securityReject(
                        "Target whitelist"
                    );


                    return true;
                }


                Serial.println(
                    "[Security 2/4] Target whitelist OK"
                );


                // =================================================
                // ACTION WHITELIST
                // =================================================

                if (
                    action != "ON"
                    &&
                    action != "OFF"
                    &&
                    action != "TOGGLE"
                )
                {
                    securityReject(
                        "Invalid action"
                    );


                    return true;
                }


                // =================================================
                // CHECK 3/4:
                // ANTI-REPLAY
                // =================================================

                uint32_t lastSeq = 0;


                bool senderSeen =
                    getLastSeenSeq(
                        sender,
                        lastSeq
                    );


                if (
                    senderSeen
                    &&
                    seq <= lastSeq
                )
                {
                    Serial.printf(
                        "[SECURITY] Replay: seq=%lu last=%lu\n",

                        static_cast<unsigned long>(
                            seq
                        ),

                        static_cast<unsigned long>(
                            lastSeq
                        )
                    );


                    securityReject(
                        "Replay / old sequence"
                    );


                    return true;
                }


                Serial.printf(
                    "[Security 3/4] Anti-replay OK: %lu > %lu\n",

                    static_cast<unsigned long>(
                        seq
                    ),

                    static_cast<unsigned long>(
                        lastSeq
                    )
                );


                // =================================================
                // CHECK 4/4:
                // HMAC-SHA256
                // =================================================

                String expectedSig =
                    computeHmacSig(
                        target,
                        action,
                        seq
                    );


                expectedSig.toLowerCase();


                Serial.printf(
                    "[Security 4/4] Expected HMAC : %s\n",
                    expectedSig.c_str()
                );


                Serial.printf(
                    "[Security 4/4] Received HMAC : %s\n",
                    sig.c_str()
                );


                if (
                    !constantTimeEquals(
                        sig,
                        expectedSig
                    )
                )
                {
                    securityReject(
                        "Invalid HMAC signature"
                    );


                    return true;
                }


                Serial.println(
                    "[Security 4/4] HMAC OK"
                );


                // =================================================
                // AUTHENTICATION SUCCESSFUL
                //
                // IMPORTANT:
                // Store sequence ONLY AFTER HMAC verification.
                // =================================================

                setLastSeenSeq(
                    sender,
                    seq
                );


                Serial.println();

                Serial.println(
                    "[SECURITY] COMMAND AUTHORIZED"
                );


                // =================================================
                // FORWARD TO SHELLY
                // =================================================

                String shellyTopic =
                    target
                    +
                    "/command/switch:0";


                String shellyPayload =
                    action;


                shellyPayload.toLowerCase();


                Serial.printf(
                    "[SHELLY] Topic   : %s\n",
                    shellyTopic.c_str()
                );


                Serial.printf(
                    "[SHELLY] Payload : %s\n",
                    shellyPayload.c_str()
                );


                publish(
                    std::string(
                        shellyTopic.c_str()
                    ),

                    std::string(
                        shellyPayload.c_str()
                    ),

                    0,
                    false
                );


                Serial.println(
                    "[SHELLY] Command published"
                );


                Serial.println(
                    "========================================"
                );


                break;
            }


            // =================================================
            // SUBSCRIBE
            // =================================================

            case Subscribe_sMQTTEventType:
            {
                sMQTTSubUnSubClientEvent* sub =
                    static_cast<
                        sMQTTSubUnSubClientEvent*
                    >(
                        event
                    );


                Serial.printf(
                    "[MQTT] Subscribe: %s\n",
                    sub->Topic().c_str()
                );


                break;
            }


            // =================================================
            // UNSUBSCRIBE
            // =================================================

            case UnSubscribe_sMQTTEventType:
            {
                break;
            }


            // =================================================
            // CONNECTION LOST
            // =================================================

            case LostConnect_sMQTTEventType:
            {
                Serial.println(
                    "[MQTT] Connection lost"
                );


                break;
            }
        }


        return true;
    }
};


// ============================================================
// BROKER INSTANCE
// ============================================================

MeshtasticBroker broker;


// ============================================================
// WIFI EVENTS
// ============================================================

void onWiFiEvent(
    WiFiEvent_t event
)
{
    switch (
        event
    )
    {

        case ARDUINO_EVENT_WIFI_AP_START:
        {
            Serial.println(
                "[WiFi] SoftAP started"
            );


            break;
        }


        case ARDUINO_EVENT_WIFI_AP_STACONNECTED:
        {
            Serial.printf(
                "[WiFi] Station connected. Clients=%d\n",
                WiFi.softAPgetStationNum()
            );


            break;
        }


        case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED:
        {
            Serial.printf(
                "[WiFi] Station disconnected. Clients=%d\n",
                WiFi.softAPgetStationNum()
            );


            break;
        }


        case ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED:
        {
            Serial.println(
                "[WiFi] Station assigned IP address"
            );


            break;
        }


        default:
        {
            break;
        }
    }
}


// ============================================================
// START WIFI ACCESS POINT
// ============================================================

bool startAccessPoint()
{
    Serial.println();

    Serial.println(
        "[WiFi] Starting ESP32 SoftAP..."
    );


    WiFi.mode(
        WIFI_AP
    );


    if (
        !WiFi.softAPConfig(
            AP_IP,
            AP_GATEWAY,
            AP_SUBNET
        )
    )
    {
        Serial.println(
            "[WiFi] ERROR: softAPConfig() failed"
        );


        return false;
    }


    bool result =
        WiFi.softAP(
            WIFI_SSID,
            WIFI_PASS
        );


    if (
        !result
    )
    {
        Serial.println(
            "[WiFi] ERROR: softAP() failed"
        );


        return false;
    }


    Serial.println();

    Serial.println(
        "========================================"
    );

    Serial.println(
        " WIFI ACCESS POINT RUNNING"
    );

    Serial.println(
        "========================================"
    );


    Serial.printf(
        "SSID       : %s\n",
        WIFI_SSID
    );


    Serial.printf(
        "IP         : %s\n",
        WiFi.softAPIP()
            .toString()
            .c_str()
    );


    Serial.printf(
        "Gateway    : %s\n",
        AP_GATEWAY
            .toString()
            .c_str()
    );


    Serial.printf(
        "MQTT       : %s:%u\n",
        WiFi.softAPIP()
            .toString()
            .c_str(),
        MQTT_PORT
    );


    Serial.println();


    return true;
}


// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(
        115200
    );


    delay(
        1000
    );


    Serial.println();

    Serial.println(
        "================================================"
    );

    Serial.println(
        " ESP32 Meshtastic Secure MQTT Gateway"
    );

    Serial.println(
        " SoftAP + sMQTTBroker + HMAC-SHA256"
    );

    Serial.println(
        "================================================"
    );


    // ========================================================
    // CONFIGURATION DIAGNOSTICS
    //
    // Do NOT print WIFI_PASS or CONTROL_SECRET.
    // ========================================================

    Serial.printf(
        "[Config] WiFi SSID       : %s\n",
        WIFI_SSID
    );


    Serial.printf(
        "[Config] Mesh region     : %s\n",
        MESH_LORA_REGION_STR
    );


    Serial.printf(
        "[Config] Gateway node ID : 0x%08lX\n",
        static_cast<unsigned long>(
            MESH_GATEWAY_NODE_ID_VAL
        )
    );


    // ========================================================
    // VALIDATE CONFIG
    // ========================================================

    if (
        strlen(
            WIFI_SSID
        )
        == 0
    )
    {
        Serial.println(
            "[Setup] ERROR: WIFI_SSID_RX is empty"
        );


        return;
    }


    if (
        strlen(
            WIFI_PASS
        )
        < 8
    )
    {
        Serial.println(
            "[Setup] ERROR: WIFI_PASS_RX must be at least 8 characters"
        );


        return;
    }


    if (
        strlen(
            CONTROL_SECRET_STR
        )
        < 16
    )
    {
        Serial.println(
            "[Setup] ERROR: CONTROL_SECRET is too short"
        );


        return;
    }


    // ========================================================
    // REGISTER WIFI EVENT HANDLER
    // ========================================================

    WiFi.onEvent(
        onWiFiEvent
    );


    // ========================================================
    // START WIFI AP
    // ========================================================

    if (
        !startAccessPoint()
    )
    {
        return;
    }


    // ========================================================
    // START MQTT BROKER
    // ========================================================

    Serial.printf(
        "[MQTT] Starting sMQTTBroker on %s:%u...\n",

        WiFi.softAPIP()
            .toString()
            .c_str(),

        MQTT_PORT
    );


    if (
        !broker.init(
            MQTT_PORT
        )
    )
    {
        Serial.println(
            "[MQTT] ERROR: broker.init() failed"
        );


        return;
    }


    Serial.println();

    Serial.println(
        "================================================"
    );

    Serial.println(
        " SECURE MQTT GATEWAY READY"
    );

    Serial.println(
        "================================================"
    );


    Serial.printf(
        "WiFi SSID : %s\n",
        WIFI_SSID
    );


    Serial.printf(
        "Broker    : mqtt://%s:%u\n",

        WiFi.softAPIP()
            .toString()
            .c_str(),

        MQTT_PORT
    );


    Serial.println();

    Serial.println(
        "Security:"
    );

    Serial.println(
        "  1. Meshtastic sender whitelist"
    );

    Serial.println(
        "  2. Shelly target whitelist"
    );

    Serial.println(
        "  3. Action whitelist"
    );

    Serial.println(
        "  4. Per-sender anti-replay"
    );

    Serial.println(
        "  5. HMAC-SHA256 authentication"
    );


    Serial.println();

    Serial.println(
        "Listening for:"
    );

    Serial.println(
        "  msh/2/json/#"
    );


    Serial.println();
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
    // Mandatory for sMQTTBroker

    broker.update();


    delay(
        1
    );
}