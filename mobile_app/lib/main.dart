import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:hive_flutter/hive_flutter.dart';

import 'core/network/api_client.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';
import 'features/auth/data/auth_repository.dart';
import 'features/auth/data/secure_token_store.dart';
import 'features/auth/presentation/bloc/auth_bloc.dart';
import 'features/payments/data/payment_repository.dart';
import 'features/payments/presentation/bloc/payments_bloc.dart';
import 'features/upload_evidence/data/upload_repository.dart';
import 'features/upload_evidence/presentation/bloc/upload_bloc.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  GoogleFonts.config.allowRuntimeFetching = true;
  await Hive.initFlutter();
  await Hive.openBox('cache');
  runApp(const MoneXaApp());
}

class MoneXaApp extends StatefulWidget {
  const MoneXaApp({super.key});

  @override
  State<MoneXaApp> createState() => _MoneXaAppState();
}

class _MoneXaAppState extends State<MoneXaApp> {
  late final AuthRepository _authRepo;
  late final AuthBloc _authBloc;
  late final PaymentRepository _paymentRepo;
  late final UploadRepository _uploadRepo;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    final store = SecureTokenStore();
    final client = ApiClient(
      readAccess: () => store.read('access'),
      readRefresh: () => store.read('refresh'),
      saveTokens: (access, refresh) async {
        await store.write('access', access);
        if (refresh != null) await store.write('refresh', refresh);
      },
    );
    ApiClient.configure(client);
    _authRepo = AuthRepository(storage: store, client: client);
    _authBloc = AuthBloc(repository: _authRepo)..add(CheckAuthStatusEvent());
    _paymentRepo = PaymentRepository(client: client);
    _uploadRepo = UploadRepository(client: client);
    _router = createRouter(_authBloc);
  }

  @override
  void dispose() {
    _authBloc.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiBlocProvider(
      providers: [
        BlocProvider.value(value: _authBloc),
        BlocProvider(create: (_) => PaymentsBloc(repository: _paymentRepo)),
        BlocProvider(create: (_) => UploadBloc(repository: _uploadRepo)),
      ],
      child: MaterialApp.router(
        title: 'MoneXa',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        routerConfig: _router,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [
          Locale('fr'),
          Locale('ee'),
          Locale('kab'),
        ],
      ),
    );
  }
}
