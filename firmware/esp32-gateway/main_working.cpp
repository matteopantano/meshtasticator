#include <Arduino.h>
#include <WiFi.h>
#include <sMQTTBroker.h>
#include <ArduinoJson.h>

// ============================================================
// Configuration from .env via load_env.py
// ============================================================

#ifndef WIFI_SSID_RX
#define WIFI_SSID_RX ""
#endif

#ifndef WIFI_PASS_RX
#define WIFI_PASS_RX ""
#endif

static const char* WIFI_SSID = WIFI_SSID_RX;
static const char* WIFI_PASS = WIFI_PASS_RX;

static const uint16_t MQTT_PORT = 1883;
static const unsigned long WIFI_CONNECT_TIMEOUT_MS = 30000;


// ============================================================
// Custom MQTT Broker
// ============================================================

class MeshtasticBroker : public sMQTTBroker
{
public:

    bool onEvent(sMQTTEvent* event) override
    {
        switch (event->Type())
        {
            // ------------------------------------------------
            // New MQTT client
            // ------------------------------------------------
            case NewClient_sMQTTEventType:
            {
                Serial.println("[MQTT] Client connected");
                break;
            }


            // ------------------------------------------------
            // MQTT client disconnected
            // ------------------------------------------------
            case RemoveClient_sMQTTEventType:
            {
                Serial.println("[MQTT] Client disconnected");
                break;
            }


            // ------------------------------------------------
            // Client published MQTT message
            // ------------------------------------------------
            case Public_sMQTTEventType:
            {
                sMQTTPublicClientEvent* pub =
                    (sMQTTPublicClientEvent*)event;

                std::string topicStd = pub->Topic();
                std::string payloadStd = pub->Payload();

                String topic(topicStd.c_str());

                // --------------------------------------------
                // Only process Meshtastic JSON topics
                //
                // Example:
                // msh/2/json/LongFast/!433ab01c
                // --------------------------------------------

                if (!topic.startsWith("msh/2/json/"))
                {
                    // Ignore binary Meshtastic traffic,
                    // Shelly status, etc.
                    return true;
                }


                Serial.println();
                Serial.println(
                    "========================================"
                );

                Serial.printf(
                    "[MESHTASTIC] Topic: %s\n",
                    topic.c_str()
                );

                Serial.printf(
                    "[MESHTASTIC] JSON: %s\n",
                    payloadStd.c_str()
                );


                // --------------------------------------------
                // Parse Meshtastic JSON
                // --------------------------------------------

                JsonDocument doc;

                DeserializationError err =
                    deserializeJson(
                        doc,
                        payloadStd.c_str()
                    );

                if (err)
                {
                    Serial.printf(
                        "[MESHTASTIC] JSON parse error: %s\n",
                        err.c_str()
                    );

                    return true;
                }


                // --------------------------------------------
                // Verify type
                // --------------------------------------------

                const char* type =
                    doc["type"] | "";

                if (strcmp(type, "text") != 0)
                {
                    Serial.printf(
                        "[MESHTASTIC] Ignoring type '%s'\n",
                        type
                    );

                    return true;
                }


                // --------------------------------------------
                // Extract command
                //
                // Incoming format:
                //
                // "payload": {
                //     "action": "ON",
                //     "seq": 517203,
                //     "sig": "b2dddd6c",
                //     "target": "shelly1-01",
                //     "ver": 1
                // }
                // --------------------------------------------

                const char* target =
                    doc["payload"]["target"] | "";

                const char* action =
                    doc["payload"]["action"] | "";

                uint32_t seq =
                    doc["payload"]["seq"] | 0;

                const char* sig =
                    doc["payload"]["sig"] | "";

                int version =
                    doc["payload"]["ver"] | 0;


                if (strlen(target) == 0 ||
                    strlen(action) == 0)
                {
                    Serial.println(
                        "[MESHTASTIC] Missing target/action"
                    );

                    return true;
                }


                Serial.printf(
                    "[COMMAND] target=%s action=%s seq=%lu "
                    "sig=%s ver=%d\n",
                    target,
                    action,
                    (unsigned long)seq,
                    sig,
                    version
                );


                // --------------------------------------------
                // Validate command
                // --------------------------------------------

                String actionString(action);

                actionString.toLowerCase();

                if (
                    actionString != "on" &&
                    actionString != "off" &&
                    actionString != "toggle"
                )
                {
                    Serial.printf(
                        "[COMMAND] Unknown action '%s'\n",
                        actionString.c_str()
                    );

                    return true;
                }


                // --------------------------------------------
                // Create Shelly topic
                //
                // shelly1-01/command/switch:0
                // --------------------------------------------

                String shellyTopic =
                    String(target) +
                    "/command/switch:0";


                Serial.println(
                    "[SHELLY] Forwarding command"
                );

                Serial.printf(
                    "[SHELLY] Topic   : %s\n",
                    shellyTopic.c_str()
                );

                Serial.printf(
                    "[SHELLY] Payload : %s\n",
                    actionString.c_str()
                );


                // --------------------------------------------
                // Publish directly from broker
                //
                // QoS = 0
                // retain = false
                // --------------------------------------------

                publish(
                    std::string(shellyTopic.c_str()),
                    std::string(actionString.c_str()),
                    0,
                    false
                );


                Serial.println(
                    "[SHELLY] Command published"
                );

                break;
            }


            // ------------------------------------------------
            // Subscription
            // ------------------------------------------------
            case Subscribe_sMQTTEventType:
            {
                sMQTTSubUnSubClientEvent* sub =
                    (sMQTTSubUnSubClientEvent*)event;

                Serial.printf(
                    "[MQTT] Subscribe: %s\n",
                    sub->Topic().c_str()
                );

                break;
            }


            // ------------------------------------------------
            // Unsubscription
            // ------------------------------------------------
            case UnSubscribe_sMQTTEventType:
            {
                break;
            }


            // ------------------------------------------------
            // WiFi / broker connection lost
            // ------------------------------------------------
            case LostConnect_sMQTTEventType:
            {
                Serial.println(
                    "[MQTT] Broker connection lost"
                );

                break;
            }
        }


        // Allow event
        return true;
    }
};


// ============================================================
// Broker instance
// ============================================================

MeshtasticBroker broker;


// ============================================================
// Wi-Fi events
// ============================================================

void onWiFiEvent(WiFiEvent_t event)
{
    switch (event)
    {
        case ARDUINO_EVENT_WIFI_STA_CONNECTED:

            Serial.println(
                "[WiFi] Connected to AP; waiting for DHCP..."
            );

            break;


        case ARDUINO_EVENT_WIFI_STA_GOT_IP:

            Serial.printf(
                "[WiFi] DHCP address: %s\n",
                WiFi.localIP().toString().c_str()
            );

            Serial.printf(
                "[WiFi] Gateway: %s\n",
                WiFi.gatewayIP().toString().c_str()
            );

            Serial.printf(
                "[WiFi] RSSI: %d dBm\n",
                WiFi.RSSI()
            );

            break;


        case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:

            Serial.println(
                "[WiFi] Disconnected"
            );

            break;


        default:
            break;
    }
}


// ============================================================
// Connect Wi-Fi
// ============================================================

bool connectWiFi()
{
    Serial.printf(
        "[WiFi] Joining '%s'...\n",
        WIFI_SSID
    );


    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);


    WiFi.begin(
        WIFI_SSID,
        WIFI_PASS
    );


    unsigned long startTime =
        millis();


    while (
        WiFi.status() != WL_CONNECTED &&
        millis() - startTime <
            WIFI_CONNECT_TIMEOUT_MS
    )
    {
        delay(250);
        Serial.print(".");
    }


    Serial.println();


    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println(
            "[WiFi] ERROR: connection timeout"
        );

        return false;
    }


    Serial.println();
    Serial.println(
        "[WiFi] Connected successfully"
    );


    Serial.printf(
        "[WiFi] IP      : %s\n",
        WiFi.localIP().toString().c_str()
    );

    Serial.printf(
        "[WiFi] Gateway : %s\n",
        WiFi.gatewayIP().toString().c_str()
    );

    return true;
}


// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);


    Serial.println();
    Serial.println(
        "========================================"
    );

    Serial.println(
        " ESP32 Meshtastic -> Shelly Gateway"
    );

    Serial.println(
        " MQTT broker: sMQTTBroker"
    );

    Serial.println(
        "========================================"
    );


    if (strlen(WIFI_SSID) == 0)
    {
        Serial.println(
            "[Setup] ERROR: WIFI_SSID_RX empty"
        );

        return;
    }


    WiFi.onEvent(onWiFiEvent);


    // --------------------------------------------------------
    // Wi-Fi
    // --------------------------------------------------------

    if (!connectWiFi())
    {
        return;
    }


    // --------------------------------------------------------
    // MQTT Broker
    // --------------------------------------------------------

    Serial.println();
    Serial.printf(
        "[MQTT] Starting broker on %s:%u...\n",
        WiFi.localIP().toString().c_str(),
        MQTT_PORT
    );


    if (!broker.init(MQTT_PORT))
    {
        Serial.println(
            "[MQTT] ERROR: broker.init() failed"
        );

        return;
    }


    Serial.println();
    Serial.println(
        "========================================"
    );

    Serial.println(
        " MQTT BROKER RUNNING"
    );

    Serial.println(
        "========================================"
    );


    Serial.printf(
        "Broker: %s:%u\n",
        WiFi.localIP().toString().c_str(),
        MQTT_PORT
    );


    Serial.println();
    Serial.println(
        "Listening for Meshtastic:"
    );

    Serial.println(
        "  msh/2/json/#"
    );


    Serial.println();
    Serial.println(
        "Command example:"
    );

    Serial.println(
        "  target = shelly1-01"
    );

    Serial.println(
        "  action = ON / OFF / TOGGLE"
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

    delay(1);
}