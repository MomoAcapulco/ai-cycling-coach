package com.aicycling.coach;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import java.util.Map;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

@RestController
@RequestMapping("/api/trainer")
public class TrainerController {
    private final RestClient client;
    private final HttpClient postClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final ObjectMapper json = new ObjectMapper();
    private final String adapterUrl;

    public TrainerController(@Value("${trainer.adapter.url:http://127.0.0.1:8766}") String adapterUrl) {
        this.adapterUrl = adapterUrl.replaceAll("/+$", "");
        this.client = RestClient.builder().baseUrl(adapterUrl).build();
    }

    @GetMapping("/telemetry")
    public ResponseEntity<?> telemetry() {
        try {
            TrainerTelemetry reading = client.get().uri("/telemetry").retrieve().body(TrainerTelemetry.class);
            if (reading == null) {
                return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(Map.of("error", "Empty adapter response"));
            }
            return ResponseEntity.ok(reading);
        } catch (RestClientException ex) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("error", "Trainer adapter is offline. Check Python adapter logs."));
        }
    }

    @GetMapping("/replay/session")
    public ResponseEntity<?> replaySession() {
        try {
            JsonNode result = client.get().uri("/replay/session").retrieve().body(JsonNode.class);
            return ResponseEntity.ok(result);
        } catch (RestClientException ex) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of("error", "Replay unavailable"));
        }
    }

    @PostMapping("/replay/control")
    public ResponseEntity<?> replayControl(@RequestBody Map<String, Object> command) {
        return sendReplay("/replay/control", command);
    }

    @PostMapping("/replay/gear")
    public ResponseEntity<?> replayGear(@RequestBody Map<String, Object> command) {
        return sendReplay("/replay/gear", command);
    }

    private ResponseEntity<?> sendReplay(String path, Map<String, Object> command) {
        try {
            // ofString publishes a body with a known Content-Length. The Python
            // BaseHTTPRequestHandler used by the trainer does not parse chunked POSTs.
            String payload = json.writeValueAsString(command);
            HttpRequest request = HttpRequest.newBuilder(URI.create(adapterUrl + path))
                    .timeout(Duration.ofSeconds(8))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();
            HttpResponse<String> response = postClient.send(
                    request, HttpResponse.BodyHandlers.ofString());
            int code = response.statusCode();
            JsonNode result = json.readTree(response.body());
            if (code >= 200 && code < 300) {
                return ResponseEntity.ok(result);
            }
            // Surface the real upstream status and response for diagnostics.
            return ResponseEntity.status(code)
                    .body(Map.of("error", "Trainer adapter rejected request",
                            "adapterStatus", code,
                            "adapterResponse", response.body()));
        } catch (JsonProcessingException ex) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(Map.of("error", "Invalid JSON: " + ex.getMessage()));
        } catch (Exception ex) {
            if (ex instanceof InterruptedException) Thread.currentThread().interrupt();
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body(Map.of("error", "Could not forward replay command",
                            "detail", ex.toString()));
        }
    }

    @GetMapping("/health")
    public Map<String, String> health() { return Map.of("status", "UP"); }
}
