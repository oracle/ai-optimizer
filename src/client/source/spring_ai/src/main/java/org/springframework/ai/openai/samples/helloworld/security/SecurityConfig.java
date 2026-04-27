package org.springframework.ai.openai.samples.helloworld.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain aiSecurityFilterChain(
            HttpSecurity http,
            ApiKeyAuthenticationFilter apiKeyAuthenticationFilter)
            throws Exception {

        return http
                .securityMatcher("/v1/**")
                .csrf(csrf -> csrf.disable())
                .cors(Customizer.withDefaults())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.GET, "/v1/service/llm").hasRole("AI_CLIENT")
                        .requestMatchers(HttpMethod.POST, "/v1/chat/completions").hasRole("AI_CLIENT")
                        .requestMatchers(HttpMethod.GET, "/v1/service/search").hasRole("AI_CLIENT")
                        .requestMatchers(HttpMethod.POST, "/v1/service/store-chunks").hasRole("AI_CLIENT")
                        .requestMatchers(HttpMethod.GET, "/v1/models").hasRole("AI_CLIENT")
                        .anyRequest().denyAll())
                .addFilterBefore(apiKeyAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)
                .build();
    }
}