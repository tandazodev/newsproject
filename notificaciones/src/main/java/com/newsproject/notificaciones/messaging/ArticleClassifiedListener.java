package com.newsproject.notificaciones.messaging;

import com.newsproject.notificaciones.service.NotificationService;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
public class ArticleClassifiedListener {

    private final NotificationService service;

    public ArticleClassifiedListener(NotificationService service) {
        this.service = service;
    }

    /**
     * Si el metodo termina bien, Spring hace ack. Un error transitorio (p. ej. la BD) se
     * propaga: nack con requeue y la cola quorum cuenta las entregas. Un mensaje invalido
     * lanza AmqpRejectAndDontRequeueException desde el servicio y va directo a la .dlq.
     */
    @RabbitListener(queues = "notificaciones.article-classified")
    public void onArticleClassified(ArticleClassifiedEvent event) {
        service.handleArticle(event);
    }
}
