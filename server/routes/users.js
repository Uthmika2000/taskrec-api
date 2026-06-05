const express = require('express');
const router = express.Router();
const userController = require('../controllers/userController');
const { authMiddleware } = require('../middleware/authMiddleware');

router.get('/',             authMiddleware, userController.getUsers);
router.get('/:id',          authMiddleware, userController.getUser);
router.patch('/:id/skills', authMiddleware, userController.updateSkills);

module.exports = router;
