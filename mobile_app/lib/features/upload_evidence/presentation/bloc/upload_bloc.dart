import 'dart:typed_data';

import 'package:flutter_bloc/flutter_bloc.dart';

import '../../data/upload_repository.dart';

abstract class UploadEvent {}

class UploadImageSubmittedEvent extends UploadEvent {
  UploadImageSubmittedEvent({required this.imageBytes, required this.filename});
  final Uint8List imageBytes;
  final String filename;
}

class UploadManualTextSubmittedEvent extends UploadEvent {
  UploadManualTextSubmittedEvent(this.text);
  final String text;
}

class ResetUploadEvent extends UploadEvent {}

abstract class UploadState {}

class UploadInitial extends UploadState {}

class UploadProcessing extends UploadState {
  UploadProcessing({this.step = 'Analyse IA en cours...'});
  final String step;
}

class UploadSuccess extends UploadState {
  UploadSuccess({required this.result});
  final Map<String, dynamic> result;
}

class UploadFailure extends UploadState {
  UploadFailure({required this.message});
  final String message;
}

class UploadBloc extends Bloc<UploadEvent, UploadState> {
  UploadBloc({required UploadRepository repository})
      : _repository = repository,
        super(UploadInitial()) {
    on<UploadImageSubmittedEvent>(_onImage);
    on<UploadManualTextSubmittedEvent>(_onText);
    on<ResetUploadEvent>((event, emit) => emit(UploadInitial()));
  }

  final UploadRepository _repository;

  Future<void> _onImage(UploadImageSubmittedEvent event, Emitter<UploadState> emit) async {
    emit(UploadProcessing(step: 'Envoi du reçu...'));
    emit(UploadProcessing(step: 'Analyse IA en cours...'));
    emit(UploadProcessing(step: 'Réconciliation...'));
    try {
      final result = await _repository.uploadEvidence(
        imageBytes: event.imageBytes,
        filename: event.filename,
      );
      emit(UploadSuccess(result: result));
    } catch (e) {
      emit(UploadFailure(message: e.toString().replaceFirst('Exception: ', '')));
    }
  }

  Future<void> _onText(UploadManualTextSubmittedEvent event, Emitter<UploadState> emit) async {
    emit(UploadProcessing(step: 'Analyse IA en cours...'));
    try {
      final result = await _repository.uploadManualText(event.text);
      emit(UploadSuccess(result: result));
    } catch (e) {
      emit(UploadFailure(message: e.toString().replaceFirst('Exception: ', '')));
    }
  }
}
