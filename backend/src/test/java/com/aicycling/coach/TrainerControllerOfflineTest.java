package com.aicycling.coach;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.net.ServerSocket;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Nothing listens on the adapter port: only this case is reported as "offline". */
@SpringBootTest
@AutoConfigureMockMvc
class TrainerControllerOfflineTest {

    @Autowired
    MockMvc mvc;

    @DynamicPropertySource
    static void adapterUrl(DynamicPropertyRegistry registry) {
        registry.add("trainer.adapter.url", () -> "http://127.0.0.1:" + freePort());
    }

    static int freePort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        } catch (IOException ex) {
            throw new IllegalStateException(ex);
        }
    }

    @Test
    void connectionRefusedIsServiceUnavailable() throws Exception {
        mvc.perform(get("/api/trainer/telemetry"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value(org.hamcrest.Matchers.startsWith("Trainer adapter is offline")));
    }
}
