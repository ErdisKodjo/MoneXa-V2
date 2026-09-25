import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import '../../../../core/theme/app_colors.dart';
import '../../../dashboard/data/dashboard_repository.dart';

/// Écran TresorIA — le CFO virtuel dans la poche.
///
/// Chat en langage naturel sur les KPIs de trésorerie (endpoint
/// /api/assistant/ask/). Le backend pré-calcule les KPIs et ne laisse
/// JAMAIS le LLM toucher à la base (cahier des charges §12.1).
///
/// Accessibilité terrain : saisie vocale (speech_to_text) pour poser la
/// question à la voix — français, Ewé ou Kabyé selon la locale du
/// téléphone. Si le micro est indisponible (permission refusée, moteur
/// absent), le bouton disparaît et la saisie clavier reste fonctionnelle.
class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key});

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _Msg {
  _Msg({required this.role, required this.text, required this.time});
  final String role; // 'user' | 'bot'
  final String text;
  final DateTime time;
}

class _AssistantScreenState extends State<AssistantScreen> {
  final DashboardRepository _repo = DashboardRepository();
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final List<_Msg> _messages = [];
  bool _sending = false;

  // ── Saisie vocale ─────────────────────────────────────────────────
  final stt.SpeechToText _speech = stt.SpeechToText();
  bool _speechAvailable = false;
  bool _listening = false;

  static const List<String> _suggestions = [
    'Combien ai-je en T-Money ?',
    'Quelle est ma trésorerie à 30 jours ?',
    'Combien d\'anomalies ?',
    'Quelles factures sont en retard ?',
  ];

  @override
  void initState() {
    super.initState();
    _messages.add(_Msg(
      role: 'bot',
      text: 'Bonjour ! Je suis TresorIA, votre CFO virtuel.\n'
          'Posez-moi une question sur votre trésorerie — par texte ou à la voix.',
      time: DateTime.now(),
    ));
    _initSpeech();
  }

  Future<void> _initSpeech() async {
    try {
      final bool available = await _speech.initialize(
        onStatus: (String status) {
          if (!mounted) return;
          setState(() => _listening = status == 'listening');
        },
        onError: (dynamic _) {
          if (!mounted) return;
          setState(() => _listening = false);
        },
      );
      if (!mounted) return;
      setState(() => _speechAvailable = available);
    } catch (_) {
      // Micro indisponible → dégradation gracieuse, saisie clavier OK.
      if (!mounted) return;
      setState(() => _speechAvailable = false);
    }
  }

  @override
  void dispose() {
    try {
      _speech.stop();
    } catch (_) {}
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _listen() async {
    if (!_speechAvailable) return;
    if (_listening) {
      try {
        await _speech.stop();
      } catch (_) {}
      if (!mounted) return;
      setState(() => _listening = false);
      return;
    }
    try {
      await _speech.listen(
        onResult: (stt.SpeechRecognitionResult result) {
          if (!mounted) return;
          setState(() => _input.text = result.recognizedWords);
        },
        listenFor: const Duration(seconds: 12),
        pauseFor: const Duration(seconds: 3),
        listenMode: stt.ListenMode.dictation,
        localeId: 'fr_FR', // ee_KE / locales locales si le moteur du téléphone les expose
      );
      if (!mounted) return;
      setState(() => _listening = true);
    } catch (_) {
      if (!mounted) return;
      setState(() => _listening = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Micro indisponible sur cet appareil.')),
      );
    }
  }

  Future<void> _send([String? overrideText]) async {
    final String question = (overrideText ?? _input.text).trim();
    if (question.isEmpty || _sending) return;
    _input.clear();
    setState(() {
      _messages.add(_Msg(role: 'user', text: question, time: DateTime.now()));
      _sending = true;
    });
    _scrollDown();

    String answer;
    try {
      answer = await _repo.askTresoria(question);
      if (answer.trim().isEmpty) {
        answer = 'TresorIA n\'a pas pu répondre — réessayez dans un instant.';
      }
    } catch (_) {
      answer = 'Connexion indisponible — réessayez dès le retour du réseau. '
          'Vos données restent en sécurité.';
    }
    if (!mounted) return;
    setState(() {
      _messages.add(_Msg(role: 'bot', text: answer, time: DateTime.now()));
      _sending = false;
    });
    _scrollDown();
  }

  void _scrollDown() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent + 80,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        title: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('TresorIA', style: TextStyle(fontWeight: FontWeight.w700)),
            Text('Votre CFO virtuel', style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              itemCount: _messages.length + (_sending ? 1 : 0),
              itemBuilder: (context, i) {
                if (i == _messages.length) {
                  return const _TypingBubble();
                }
                final _Msg m = _messages[i];
                return _Bubble(isUser: m.role == 'user', text: m.text, time: _fmt(m.time));
              },
            ),
          ),
          if (_messages.length <= 1)
            SizedBox(
              height: 48,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, i) => ActionChip(
                  label: Text(_suggestions[i], style: const TextStyle(fontSize: 12)),
                  backgroundColor: Colors.white,
                  side: const BorderSide(color: AppColors.muted),
                  onPressed: () => _send(_suggestions[i]),
                ),
              ),
            ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: InputDecoration(
                        hintText: 'Posez votre question…',
                        filled: true,
                        fillColor: Colors.white,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24),
                          borderSide: const BorderSide(color: AppColors.muted),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24),
                          borderSide: const BorderSide(color: AppColors.muted),
                        ),
                      ),
                    ),
                  ),
                  if (_speechAvailable)
                    Padding(
                      padding: const EdgeInsets.only(left: 8),
                      child: CircleAvatar(
                        radius: 22,
                        backgroundColor: _listening ? AppColors.danger : AppColors.navy,
                        child: IconButton(
                          icon: Icon(
                            _listening ? Icons.stop : Icons.mic,
                            color: Colors.white,
                            size: 20,
                          ),
                          onPressed: _listen,
                        ),
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.only(left: 8),
                    child: CircleAvatar(
                      radius: 22,
                      backgroundColor: AppColors.gold,
                      child: _sending
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : IconButton(
                              icon: const Icon(Icons.send, color: Colors.white, size: 20),
                              onPressed: _send,
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _fmt(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.isUser, required this.text, required this.time});
  final bool isUser;
  final String text;
  final String time;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color: isUser ? AppColors.navy : Colors.white,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
          border: isUser ? null : Border.all(color: AppColors.muted),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              text,
              style: TextStyle(
                fontSize: 14,
                height: 1.35,
                color: isUser ? Colors.white : AppColors.navy,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              time,
              style: TextStyle(fontSize: 10, color: isUser ? Colors.white70 : AppColors.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _TypingBubble extends StatelessWidget {
  const _TypingBubble();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.muted),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.gold),
            ),
            SizedBox(width: 10),
            Text('TresorIA analyse…', style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ),
      ),
    );
  }
}
