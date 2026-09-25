import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:image_picker/image_picker.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/utils/formatters.dart';
import '../../../../shared/widgets/status_badge.dart';
import '../bloc/upload_bloc.dart';

class UploadEvidenceScreen extends StatefulWidget {
  const UploadEvidenceScreen({super.key});

  @override
  State<UploadEvidenceScreen> createState() => _UploadEvidenceScreenState();
}

class _UploadEvidenceScreenState extends State<UploadEvidenceScreen> {
  final _textCtrl = TextEditingController();
  final _picker = ImagePicker();

  @override
  void dispose() {
    _textCtrl.dispose();
    super.dispose();
  }

  Future<void> _pick(ImageSource source) async {
    final file = await _picker.pickImage(source: source, imageQuality: 85);
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    context.read<UploadBloc>().add(
          UploadImageSubmittedEvent(imageBytes: bytes, filename: file.name),
        );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Photographier un reçu')),
      body: BlocBuilder<UploadBloc, UploadState>(
        builder: (context, state) {
          if (state is UploadProcessing) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const CircularProgressIndicator(color: AppColors.gold),
                  const SizedBox(height: 16),
                  Text(
                    state.step,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  const Text('Analyse IA en cours...', style: TextStyle(color: AppColors.muted)),
                ],
              ),
            );
          }
          if (state is UploadSuccess) {
            final r = state.result;
            return Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Reçu extrait', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 16),
                  Text(Formatters.formatFcfa(r['amount']), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: AppColors.primary)),
                  const SizedBox(height: 8),
                  StatusBadge(status: '${r['channel'] ?? ''}', isChannel: true),
                  const SizedBox(height: 12),
                  Text('Réf. ${r['provider_ref'] ?? '—'}'),
                  Text('Payeur : ${r['payer_name'] ?? '—'}'),
                  Text('Confiance IA : ${Formatters.formatPercent(r['ai_confidence'])}'),
                  const SizedBox(height: 8),
                  StatusBadge(status: '${r['status'] ?? 'A_VALIDER'}'),
                  const Spacer(),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () => context.read<UploadBloc>().add(ResetUploadEvent()),
                      child: const Text('Nouveau reçu'),
                    ),
                  ),
                ],
              ),
            );
          }
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const Text(
                'Capturez un SMS T-Money, Moov ou Flooz. L’IA extrait montant, référence et payeur.',
                style: TextStyle(color: AppColors.muted),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: () => _pick(ImageSource.camera),
                icon: const Icon(Icons.photo_camera_outlined),
                label: const Text('Prendre une photo'),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: () => _pick(ImageSource.gallery),
                icon: const Icon(Icons.photo_library_outlined),
                label: const Text('Choisir une image'),
              ),
              const SizedBox(height: 28),
              const Text('Plan B — coller le SMS', style: TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              TextField(
                controller: _textCtrl,
                maxLines: 4,
                decoration: const InputDecoration(hintText: 'Paiement reçu de ... FCFA Ref TMX...'),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () {
                  if (_textCtrl.text.trim().isEmpty) return;
                  context.read<UploadBloc>().add(UploadManualTextSubmittedEvent(_textCtrl.text.trim()));
                },
                child: const Text('Analyser le texte'),
              ),
              if (state is UploadFailure) ...[
                const SizedBox(height: 16),
                Text(state.message, style: const TextStyle(color: AppColors.danger)),
              ],
            ],
          );
        },
      ),
    );
  }
}
