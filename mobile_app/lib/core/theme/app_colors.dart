import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  static const Color primary = Color(0xFF063082);
  static const Color navy = Color(0xFF1A2539);
  static const Color cream = Color(0xFFFFFBF4);
  static const Color gold = Color(0xFFF59E0B);
  static const Color success = Color(0xFF059669);
  static const Color danger = Color(0xFFDC2626);
  static const Color muted = Color(0xFF9DA9C3);
  static const Color border = Color(0xFFCBD5E1);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color especes = Color(0xFF2C3E5A);

  static Color channelColor(String channel) {
    switch (channel.toUpperCase()) {
      case 'TMONEY':
        return primary;
      case 'MOOV':
        return success;
      case 'FLOOZ':
        return gold;
      case 'BANQUE':
        return muted;
      case 'ESPECES':
        return especes;
      default:
        return primary;
    }
  }
}
