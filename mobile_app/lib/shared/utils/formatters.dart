import 'package:intl/intl.dart';

class Formatters {
  Formatters._();

  static String formatFcfa(dynamic amount) {
    if (amount == null) return '0 FCFA';
    final num value = amount is num ? amount : num.tryParse(amount.toString()) ?? 0;
    final digits = value.round().toString();
    final reversed = digits.split('').reversed.toList();
    final chunks = <String>[];
    for (var i = 0; i < reversed.length; i += 3) {
      final end = (i + 3 < reversed.length) ? i + 3 : reversed.length;
      chunks.add(reversed.sublist(i, end).reversed.join());
    }
    return '${chunks.reversed.join(' ')} FCFA';
  }

  static String formatShortDate(dynamic value) {
    if (value == null) return '—';
    DateTime? date;
    if (value is DateTime) {
      date = value;
    } else if (value is String) {
      date = DateTime.tryParse(value);
    }
    if (date == null) return '—';
    return DateFormat('dd/MM/yyyy').format(date);
  }

  static String formatPercent(dynamic value) {
    if (value == null) return '—';
    final num n = value is num ? value : num.tryParse(value.toString()) ?? 0;
    return '${(n * 100).round()}%';
  }
}
