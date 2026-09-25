import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';

class StatusBadge extends StatelessWidget {
  const StatusBadge({
    super.key,
    required this.status,
    this.isChannel = false,
  });

  final String status;
  final bool isChannel;

  @override
  Widget build(BuildContext context) {
    final Color color;
    final String label;
    if (isChannel) {
      color = AppColors.channelColor(status);
      label = status;
    } else {
      switch (status) {
        case 'RECONCILIE':
          color = AppColors.success;
          label = 'Réconcilié';
          break;
        case 'A_VALIDER':
          color = AppColors.gold;
          label = 'À valider';
          break;
        case 'ANOMALIE':
          color = AppColors.danger;
          label = 'Anomalie';
          break;
        case 'NON_RATTACHE':
          color = AppColors.muted;
          label = 'Non rattaché';
          break;
        default:
          color = AppColors.muted;
          label = status;
      }
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
