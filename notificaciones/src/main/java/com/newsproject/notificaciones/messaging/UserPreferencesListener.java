package com.newsproject.notificaciones.messaging;

import com.newsproject.notificaciones.service.NotificationService;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class UserPreferencesListener {

    private final NotificationService service;

    public UserPreferencesListener(NotificationService service) {
        this.service = service;
    }

    @RabbitListener(queues = "notificaciones.user-preferences-updated")
    public void onPreferencesUpdated(UserPreferencesUpdatedEvent event) {
        service.handlePreferences(event);
    }
}
